"""Screen bodies. One Screen.show() for every bubble."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import asyncpg
from PIL import Image

from app.api.max_api import delete_message, edit_message, mid_from_send, send_file, send_message
from app.database.repos import channels as ch_repo
from app.database.repos import jobs as jobs_repo
from app.database.repos import tails as tails_repo
from app.database.repos import templates as tpl_repo
from app.engine.apply import tmp_path
from app.engine.image import apply_watermark, contact_sheet, save_jpeg
from app.keyboards.builders import (
    POSITION_LABELS,
    cancel_channel_wait_kb,
    cancel_tail_wait_kb,
    cancel_wait_kb,
    channel_card_kb,
    channels_list_kb,
    confirm_delete_tail_kb,
    confirm_delete_tpl_kb,
    opacity_kb,
    pad_kb,
    position_kb,
    profile_kb,
    rotation_kb,
    tail_card_kb,
    tails_list_kb,
    template_card_kb,
    templates_list_kb,
    width_kb,
)
from app.models import Channel, DayStats, Tail, Template, User


@dataclass
class Screen:
    max_user_id: int
    replace_mid: Optional[str] = None

    @classmethod
    def for_user(cls, user: User, replace_mid: Optional[str] = None) -> Screen:
        return cls(max_user_id=user.max_user_id, replace_mid=replace_mid)

    async def show(
        self, text: str, kb: List, photo: Optional[Path] = None
    ) -> Optional[str]:
        mid = self.replace_mid
        if mid and photo is None and kb:
            try:
                await edit_message(mid, text, kb)
                return mid
            except RuntimeError:
                pass
        if mid:
            if not await delete_message(mid):
                return mid
        if photo is not None:
            r = await send_file(
                str(photo),
                kind="image",
                caption=text,
                keyboard=kb,
                user_id=self.max_user_id,
            )
            if r:
                return mid_from_send(r)
        r = await send_message(user_id=self.max_user_id, text=text, keyboard=kb)
        return mid_from_send(r)


def _pos_label(code: str) -> str:
    return POSITION_LABELS.get(code, code)


def templates_body(n: int) -> str:
    if n == 0:
        return (
            "**Шаблоны**\n\n"
            "Нет шаблонов.\n"
            "Нажмите «+ Новый» и пришлите картинку водяного знака."
        )
    return (
        "**Шаблоны**\n\n"
        "Галочка — текущий знак. Карандаш — настройки.\n"
        "Киньте фото или видео в чат — наложу дефолтный шаблон."
    )


def template_card_body(t: Template) -> str:
    return (
        f"**{t.name}**\n"
        f"Расположение: {_pos_label(t.position)}\n"
        f"Ширина: {t.width_pct}%\n"
        f"Прозрачность: {t.opacity}%\n"
        f"Поворот: {t.rotation_deg}°\n"
        f"Отступ: X={t.pad_x} Y={t.pad_y}"
    )


def tails_body(n: int, enabled: bool) -> str:
    lines = [
        "**Хвосты**",
        "",
        "Видеохвостик — короткий ролик, добавляемый в начале или в конце основного видео.",
    ]
    if n == 0:
        lines += ["", "Нет видеохостиков"]
    if not enabled:
        lines += ["", "Сейчас: не использовать."]
    return "\n".join(lines)


def tail_card_body(t: Tail) -> str:
    place = "в начало" if t.placement == "start" else "в конец"
    return f"**{t.name}**\nКуда: {place}"


def channels_body(n: int) -> str:
    if n == 0:
        return (
            "**Каналы**\n\n"
            "Всего: 0\n\n"
            "Добавьте бота админом канала, затем нажмите «+ Канал» "
            "и перешлите любой пост из этого канала."
        )
    return f"**Каналы**\n\nВсего: {n}\n\nНажмите канал, чтобы открыть настройки."


def channel_card_body(c: Channel) -> str:
    st = "вкл" if c.enabled else "выкл"
    tail = "вкл" if c.use_tail else "выкл"
    return (
        f"**{c.title or c.chat_id}**\n"
        f"Авто: {st}\n"
        f"Хвост: {tail}\n"
        "Шаблон ниже — какой знак вешать на посты."
    )


def profile_body(user: User, stats: DayStats) -> str:
    n = stats.bytes_out
    if n < 1024:
        traffic = f"{n} Б"
    elif n < 1024 * 1024:
        traffic = f"{n / 1024:.1f} КБ"
    else:
        traffic = f"{n / (1024 * 1024):.2f} МБ"
    return (
        f"**Профиль**\n\n"
        f"{user.name or '—'}\n"
        f"ID: {user.max_user_id}\n\n"
        f"Тариф: демо\n\n"
        f"**Сегодня**\n"
        f"Трафик: {traffic}\n"
        f"Фото / видео: {stats.photos} / {stats.videos}"
    )


def _preview_path(t: Template) -> Optional[Path]:
    src = Path(t.file_path)
    if not src.exists():
        return None
    dest = tmp_path(t.user_id, "-card.jpg")
    try:
        plate = Image.new("RGB", (720, 720), (30, 32, 38))
        img = apply_watermark(plate, src, t.overlay())
        save_jpeg(img, dest)
        return dest
    except Exception:
        dest.unlink(missing_ok=True)
        return src if src.suffix.lower() in {".jpg", ".jpeg", ".png"} else None


async def show_templates(pool: asyncpg.Pool, user: User, ui: Screen) -> Optional[str]:
    tpls = await tpl_repo.list_for(pool, user.id)
    photo = None
    if tpls:
        paths = [Path(t.file_path) for t in tpls if Path(t.file_path).exists()]
        if paths:
            photo = tmp_path(user.id, "-sheet.jpg")
            save_jpeg(contact_sheet(paths), photo)
    try:
        return await ui.show(templates_body(len(tpls)), templates_list_kb(tpls), photo)
    finally:
        if photo is not None:
            photo.unlink(missing_ok=True)


async def show_template_card(
    pool: asyncpg.Pool, user: User, t: Template, ui: Screen
) -> Optional[str]:
    photo = _preview_path(t)
    try:
        return await ui.show(template_card_body(t), template_card_kb(t), photo)
    finally:
        if photo is not None and photo != Path(t.file_path):
            photo.unlink(missing_ok=True)


async def show_tails(pool: asyncpg.Pool, user: User, ui: Screen) -> Optional[str]:
    items = await tails_repo.list_for(pool, user.id)
    enabled = await tails_repo.tails_enabled(pool, user.id)
    return await ui.show(tails_body(len(items), enabled), tails_list_kb(items, enabled))


async def show_tail_card(
    pool: asyncpg.Pool, user: User, t: Tail, ui: Screen
) -> Optional[str]:
    return await ui.show(tail_card_body(t), tail_card_kb(t))


async def show_channels(pool: asyncpg.Pool, user: User, ui: Screen) -> Optional[str]:
    items = await ch_repo.list_for(pool, user.id)
    return await ui.show(channels_body(len(items)), channels_list_kb(items))


async def show_channel_card(
    pool: asyncpg.Pool, user: User, c: Channel, ui: Screen
) -> Optional[str]:
    tpls = await tpl_repo.list_for(pool, user.id)
    return await ui.show(channel_card_body(c), channel_card_kb(c, tpls))


async def show_profile(pool: asyncpg.Pool, user: User, ui: Screen) -> Optional[str]:
    stats = await jobs_repo.today_stats(pool, user.id)
    return await ui.show(profile_body(user, stats), profile_kb())


async def ask_new_template(user: User, ui: Screen) -> Optional[str]:
    return await ui.show(
        "Пришлите картинку водяного знака (лучше PNG с прозрачностью).",
        cancel_wait_kb(),
    )


async def ask_new_tail(user: User, ui: Screen) -> Optional[str]:
    return await ui.show("Пришлите короткий ролик — до 15 секунд.", cancel_tail_wait_kb())


async def ask_bind_channel(user: User, ui: Screen) -> Optional[str]:
    return await ui.show(
        "Добавьте бота админом канала и перешлите сюда любой пост из него.",
        cancel_channel_wait_kb(),
    )


async def show_position_picker(ui: Screen, tid: int) -> Optional[str]:
    return await ui.show("Куда поставить водяной знак", position_kb(tid))


async def show_width_picker(ui: Screen, tid: int) -> Optional[str]:
    return await ui.show("Ширина знака (% кадра)", width_kb(tid))


async def show_opacity_picker(ui: Screen, tid: int) -> Optional[str]:
    return await ui.show("Прозрачность", opacity_kb(tid))


async def show_rotation_picker(ui: Screen, tid: int) -> Optional[str]:
    return await ui.show("Поворот", rotation_kb(tid))


async def show_pad_picker(ui: Screen, tid: int, axis: str) -> Optional[str]:
    title = "Сдвиг по X (% кадра)" if axis == "x" else "Сдвиг по Y (% кадра)"
    return await ui.show(title, pad_kb(tid, axis))


async def show_delete_tpl(ui: Screen, tid: int) -> Optional[str]:
    return await ui.show("Удалить этот шаблон?", confirm_delete_tpl_kb(tid))


async def show_delete_tail(ui: Screen, tid: int) -> Optional[str]:
    return await ui.show("Удалить этот хвост?", confirm_delete_tail_kb(tid))
