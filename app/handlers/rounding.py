"""Rounding screens, input states and original PNG downloads."""
from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections import defaultdict
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.api import max_api
from app.engine.apply import tmp_path, user_dir
from app.engine.rounding import DEFAULT_SIZE, parse_size, preview_image, round_image
from app.keyboards.builders import BTN_BACK, btn
from app.models import User
from app.renderers.views import PNG_FILE_NOTE, PROCESSING_IMAGE, Screen
from app.schemas.updates import extract_media_items, extract_text
from app.wait import clear_wait, get_wait, set_wait

WAIT_ROUND_SIZE = "WAIT_ROUND_SIZE"
WAIT_ROUND_IMAGE = "WAIT_ROUND_IMAGE"
RESULT_TTL = 10 * 60
BODY = (
    "🌝 **Округление**\n\n"
    "Настройте округление вручную или примените стандартные параметры (1254 × 1254), "
    "чтобы изображение хорошо смотрелось даже в миниатюре."
)
CUSTOM_PROMPT = (
    "Укажите размер изображения, ширина и высота должны быть одинаковыми.\n\n"
    "**Пример формата:**\n> 600 600\n> 300x300"
)
PROCESSING = PROCESSING_IMAGE

# max_user_id → (requested size, current prompt/menu message id)
_inputs: dict[int, tuple[int, str | None]] = {}
_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


def _directory(user: User) -> Path:
    path = user_dir(user.id) / "rounding"
    path.mkdir(exist_ok=True)
    return path


def _source(result: Path) -> Path:
    return result.with_name(result.stem + ".source")


def _result(user: User, key: str) -> Path | None:
    if not re.fullmatch(r"[0-9a-f]{32}", key):
        return None
    path = _directory(user) / f"{key}.png"
    try:
        modified = path.stat().st_mtime
    except FileNotFoundError:
        return None
    if time.time() - modified >= RESULT_TTL:
        path.unlink(missing_ok=True)
        _source(path).unlink(missing_ok=True)
        return None
    return path


def _latest(user: User) -> Path | None:
    index = _directory(user) / "latest"
    return _result(user, index.read_text()) if index.is_file() else None


def reset_download(user: User) -> None:
    result = _latest(user)
    (_directory(user) / "download_hidden").write_text(result.stem if result else "")


def keyboard(result: Path | None) -> list:
    rows = [[btn("Стандартный", "round:standard")], [btn("Свой размер", "round:custom")]]
    if result:
        rows.append([btn("📥 Скачать изображение", f"round:download:{result.stem}")])
        if _source(result).is_file():
            rows.append([btn("Сброс", "round:reset")])
    rows.append([btn(BTN_BACK, "nav:home")])
    return rows


def _back() -> list:
    return [[btn(BTN_BACK, "round:menu")]]


async def show(pool, user: User, ui: Screen) -> str | None:
    result = _latest(user)
    hidden = _directory(user) / "download_hidden"
    download = result if result and (not hidden.is_file() or hidden.read_text() != result.stem) else None
    preview = tmp_path(user.id, ".jpg")
    try:
        if result:
            with Image.open(result) as image:
                preview_image(image, image.width).save(preview, "JPEG", quality=95)
        else:
            preview_image().save(preview, "JPEG", quality=95)
        return await ui.show(BODY, keyboard(download), preview)
    finally:
        preview.unlink(missing_ok=True)


async def standard(pool, user: User, ui: Screen, args) -> None:
    await _ask_image(user, ui, DEFAULT_SIZE, "ℹ️ Загрузите изображения формата PNG.")


async def custom(pool, user: User, ui: Screen, args) -> None:
    set_wait(user.max_user_id, WAIT_ROUND_SIZE)
    mid = await ui.show(CUSTOM_PROMPT, _back())
    _inputs[user.max_user_id] = (DEFAULT_SIZE, mid)


async def _ask_image(user: User, ui: Screen, size: int, text: str) -> None:
    set_wait(user.max_user_id, WAIT_ROUND_IMAGE)
    mid = await ui.show(text + "\n\n" + PNG_FILE_NOTE, _back())
    _inputs[user.max_user_id] = (size, mid)


async def ingest_size(pool, user: User, update: dict) -> None:
    try:
        size = parse_size(extract_text(update))
    except ValueError as exc:
        await max_api.send_to_user(user.max_user_id, str(exc))
        return
    _, mid = _inputs.get(user.max_user_id, (DEFAULT_SIZE, None))
    await _ask_image(user, Screen.for_user(user, mid), size,
                     "ℹ️ Теперь, загрузите изображения формата PNG.")


def _save(user: User, data: bytes, size: int) -> Path:
    result = round_image(data, size)
    dest = _directory(user) / f"{uuid.uuid4().hex}.png"
    result.save(dest, "PNG")
    _source(dest).write_bytes(data)
    index = dest.with_suffix(".latest")
    index.write_text(dest.stem)
    index.replace(dest.parent / "latest")
    return dest


async def ingest_images(pool, user: User, update: dict) -> None:
    async with _locks[user.max_user_id]:
        if get_wait(user.max_user_id) != WAIT_ROUND_IMAGE:
            return
        items = [p for kind, p in extract_media_items(update) if kind == "photo"]
        if not items:
            await max_api.send_to_user(user.max_user_id, "Нужна картинка. Пришлите файл или фото.")
            return
        size, mid = _inputs.get(user.max_user_id, (DEFAULT_SIZE, None))
        original_input = (size, mid)
        succeeded = False
        ui = Screen.for_user(user, mid)
        for payload in items:
            progress_mid = await ui.show(PROCESSING, [])
            ui = Screen.for_user(user, progress_mid)
            data = await max_api.download_payload(payload)
            try:
                if not data:
                    raise ValueError("Не скачал картинку, попробуйте ещё раз.")
                await asyncio.to_thread(_save, user, data, size)
            except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError):
                mid = await ui.show("Не получилось обработать изображение. Попробуйте ещё раз.", _back())
                ui = Screen.for_user(user, mid)
                continue
            mid = await show(pool, user, ui)
            succeeded = True
            # Keep each image in a multi-photo message available through its own menu.
            ui = Screen.for_user(user, fresh=True)
        if (get_wait(user.max_user_id) == WAIT_ROUND_IMAGE
                and _inputs.get(user.max_user_id) == original_input):
            if succeeded:
                clear_wait(user.max_user_id)
                _inputs.pop(user.max_user_id, None)
            else:
                set_wait(user.max_user_id, WAIT_ROUND_IMAGE)
                _inputs[user.max_user_id] = (size, mid)


async def download(pool, user: User, ui: Screen, args) -> None:
    result = _result(user, args[0]) if args else None
    if result:
        await max_api.send_file(str(result), kind="file", user_id=user.max_user_id)
    else:
        clear_wait(user.max_user_id)
        await show(pool, user, ui)


async def reset(pool, user: User, ui: Screen, args) -> None:
    result = _latest(user)
    bak = _source(result) if result else None
    if result and bak is not None and bak.is_file():
        try:
            with Image.open(bak) as image:
                image.convert("RGBA").save(result, "PNG")
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError):
            pass
    await show(pool, user, ui)
