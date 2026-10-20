"""Background removal screens and original PNG downloads."""
from __future__ import annotations

import asyncio
import re
import uuid
from collections import defaultdict
from pathlib import Path

from PIL import Image

from app.api import max_api
from app.engine.apply import tmp_path, user_dir
from app.engine.background import preview_image
from app.engine import background as engine
from app.keyboards.builders import BTN_BACK, btn
from app.models import User
from app.renderers.views import PNG_FILE_NOTE, PROCESSING_IMAGE, Screen
from app.schemas.updates import extract_media_items
from app.wait import clear_wait, get_wait, set_wait

WAIT_BG_IMAGE = "WAIT_BG_IMAGE"
BODY = "◻️ **Убрать фон**\n\nЗагрузите изображение, мы удалим фон и сохраним главное."
PROCESSING = PROCESSING_IMAGE
_inputs: dict[int, str | None] = {}
_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


def _directory(user: User) -> Path:
    path = user_dir(user.id) / "background"
    path.mkdir(exist_ok=True)
    return path


def _result(user: User, key: str) -> Path | None:
    if not re.fullmatch(r"[0-9a-f]{32}", key):
        return None
    path = _directory(user) / f"{key}.png"
    return path if path.is_file() else None


def _latest(user: User) -> Path | None:
    index = _directory(user) / "latest"
    return _result(user, index.read_text()) if index.is_file() else None


def reset_download(user: User) -> None:
    result = _latest(user)
    (_directory(user) / "download_hidden").write_text(result.stem if result else "")


def keyboard(result: Path | None) -> list:
    rows = [[btn("➕ Загрузить", "bg:upload")]]
    if result:
        rows.append([btn("📥 Скачать изображение", f"bg:download:{result.stem}")])
    rows.append([btn(BTN_BACK, "nav:home")])
    return rows


async def show(pool, user: User, ui: Screen) -> str | None:
    result = _latest(user)
    hidden = _directory(user) / "download_hidden"
    download = result if result and (not hidden.is_file() or hidden.read_text() != result.stem) else None
    preview = tmp_path(user.id, ".jpg")
    try:
        if result:
            with Image.open(result) as image:
                preview_image(image).save(preview, "JPEG", quality=95)
        else:
            preview_image().save(preview, "JPEG", quality=95)
        return await ui.show(BODY, keyboard(download), preview)
    finally:
        preview.unlink(missing_ok=True)


async def upload(pool, user: User, ui: Screen, args) -> None:
    set_wait(user.max_user_id, WAIT_BG_IMAGE)
    mid = await ui.show("ℹ️ Загрузите изображения формата PNG.\n\n" + PNG_FILE_NOTE,
                        [[btn(BTN_BACK, "bg:menu")]])
    _inputs[user.max_user_id] = mid


def _save(user: User, data: bytes) -> Path:
    result = engine.remove_background(data)
    dest = _directory(user) / f"{uuid.uuid4().hex}.png"
    result.save(dest, "PNG")
    index = dest.with_suffix(".latest")
    index.write_text(dest.stem)
    index.replace(dest.parent / "latest")
    return dest


async def ingest_images(pool, user: User, update: dict) -> None:
    async with _locks[user.max_user_id]:
        if get_wait(user.max_user_id) != WAIT_BG_IMAGE:
            return
        items = [payload for kind, payload in extract_media_items(update) if kind == "photo"]
        if not items:
            await max_api.send_to_user(user.max_user_id, "Нужна картинка. Пришлите файл или фото.")
            return
        original_mid = _inputs.get(user.max_user_id)
        mid, succeeded = original_mid, False
        ui = Screen.for_user(user, mid)
        for payload in items:
            mid = await ui.show(PROCESSING, [])
            ui = Screen.for_user(user, mid)
            try:
                data = await max_api.download_payload(payload)
                if not data:
                    raise ValueError("Empty image download")
                await asyncio.to_thread(_save, user, data)
            except Exception as exc:
                print("background removal failed:", type(exc).__name__)
                mid = await ui.show("Не получилось обработать изображение. Попробуйте ещё раз.",
                                    [[btn(BTN_BACK, "bg:menu")]])
                ui = Screen.for_user(user, mid)
                continue
            succeeded = True
            mid = await show(pool, user, ui)
            ui = Screen.for_user(user, fresh=True)
        if get_wait(user.max_user_id) == WAIT_BG_IMAGE and _inputs.get(user.max_user_id) == original_mid:
            if succeeded:
                clear_wait(user.max_user_id)
                _inputs.pop(user.max_user_id, None)
            else:
                set_wait(user.max_user_id, WAIT_BG_IMAGE)
                _inputs[user.max_user_id] = mid


async def download(pool, user: User, ui: Screen, args) -> None:
    result = _result(user, args[0]) if args else None
    if result:
        await max_api.send_file(str(result), kind="file", user_id=user.max_user_id)
    else:
        clear_wait(user.max_user_id)
        await show(pool, user, ui)
