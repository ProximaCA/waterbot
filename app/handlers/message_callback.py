from __future__ import annotations

import asyncio
import io
from dataclasses import replace
from pathlib import Path
from typing import Awaitable, Callable, Optional, Sequence

import asyncpg
from PIL import Image, ImageOps, UnidentifiedImageError

from app import state
from app.engine.background import remove_background
from app.engine.rounding import MAX_SIZE, round_image
from app.handlers import background, rounding
from app.api.max_api import answer_callback
from app.database.repos import channels as ch_repo
from app.database.repos import tails as tails_repo
from app.database.repos import templates as tpl_repo
from app.database.repos import users as user_repo
from app.models import User
from app.keyboards.builders import POSITION_LABELS
from app.renderers import views
from app.renderers.views import Screen
from app.schemas.updates import extract_message_mid, parse_message_callback
from app.wait import (
    WAIT_CHANNEL_FORWARD,
    WAIT_TAIL_VIDEO,
    WAIT_WM_IMAGE,
    clear_wait,
    set_wait,
)

Handler = Callable[
    [asyncpg.Pool, User, Screen, Sequence[str]], Awaitable[None]
]


def parse_payload(p: str) -> tuple[str, list[str]]:
    parts = [x for x in p.split(":") if x != ""]
    if not parts:
        return "", []
    if len(parts) == 1:
        return parts[0], []
    return f"{parts[0]}:{parts[1]}", parts[2:]


def _int(s: str) -> Optional[int]:
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def _tid(args: Sequence[str]) -> Optional[int]:
    return _int(args[0]) if args else None


def _tab(show) -> Handler:
    async def h(pool, user, ui, args):
        clear_wait(user.max_user_id)
        await show(pool, user, ui)

    return h


def _open(repo, card, listing, *extra) -> Handler:
    async def h(pool, user, ui, args):
        tid = _tid(args)
        item = await repo.get(pool, tid, user.id) if tid else None
        if not item:
            await listing(pool, user, ui)
            return
        await card(pool, user, item, ui, *extra)

    return h


def _use(set_default, get, card, listing) -> Handler:
    async def h(pool, user, ui, args):
        tid = _tid(args)
        if tid:
            await set_default(pool, tid, user.id)
            item = await get(pool, tid, user.id)
            if item:
                await card(pool, user, item, ui)
                return
        await listing(pool, user, ui)

    return h


def _delok(delete, listing) -> Handler:
    async def h(pool, user, ui, args):
        tid = _tid(args)
        if tid:
            path = await delete(pool, tid, user.id)
            if path:
                Path(path).unlink(missing_ok=True)
        await listing(pool, user, ui)

    return h


def _ask(kind, show) -> Handler:
    async def h(pool, user, ui, args):
        set_wait(user.max_user_id, kind)
        await show(user, ui)

    return h


def _set(save, card, listing, conv=str, extra=()) -> Handler:
    async def h(pool, user, ui, args):
        tid = _tid(args)
        if tid is None or len(args) < 2:
            await listing(pool, user, ui)
            return
        try:
            val = conv(args[1])
        except (TypeError, ValueError):
            await listing(pool, user, ui)
            return
        item = await save(pool, tid, user.id, val)
        if item:
            await card(pool, user, item, ui, *extra)
        else:
            await listing(pool, user, ui)

    return h


def _toggle(get, apply, card, listing) -> Handler:
    async def h(pool, user, ui, args):
        tid = _tid(args)
        item = await get(pool, tid, user.id) if tid else None
        if not item:
            await listing(pool, user, ui)
            return
        item = await apply(pool, user, item)
        if item:
            await card(pool, user, item, ui)
        else:
            await listing(pool, user, ui)

    return h


def _as_position(s: str) -> str:
    if s not in POSITION_LABELS:
        raise ValueError(s)
    return s


def _tpl_field(field, conv, card=views.show_template_card, extra=()) -> Handler:
    async def save(pool, tid, user_id, val):
        return await tpl_repo.update(pool, tid, user_id, **{field: val})

    return _set(save, card, views.show_templates, conv, extra)


async def _save_ch_tpl(pool, cid, user_id, raw):
    tpl_id = None if not raw else raw
    return await ch_repo.set_template(pool, cid, user_id, tpl_id)


async def _flip_enabled(pool, user, c):
    return await ch_repo.set_enabled(pool, c.id, user.id, not c.enabled)


async def _flip_tail(pool, user, c):
    return await ch_repo.set_use_tail(pool, c.id, user.id, not c.use_tail)


async def _tail_off(pool, user, ui, args):
    await tails_repo.set_tails_enabled(pool, user.id, False)
    await views.show_tails(pool, user, ui)


async def _select_template(pool, user, ui, args):
    clear_wait(user.max_user_id)
    tid = _tid(args)
    if tid:
        await tpl_repo.set_default(pool, tid, user.id)
    await views.show_templates(pool, user, ui)


async def _new_template(pool, user, ui, args):
    clear_wait(user.max_user_id)
    state.TEMPLATE_UPLOAD.pop(user.max_user_id, None)
    templates = await tpl_repo.list_for(pool, user.id)
    occupied = {t.slot for t in templates}
    slot = _tid(args) if args else next((s for s in range(1, 4) if s not in occupied), None)
    if slot not in (1, 2, 3) or slot in occupied:
        await views.show_templates(pool, user, ui)
        return
    set_wait(user.max_user_id, WAIT_WM_IMAGE)
    mid = await views.ask_new_template(user, ui)
    state.TEMPLATE_UPLOAD[user.max_user_id] = (slot, mid)


async def _templates_back(pool, user, ui, args):
    clear_wait(user.max_user_id)
    key, back_args = state.TEMPLATE_RETURN.get(user.max_user_id, ("nav:home", []))
    await ROUTES[key](pool, user, ui, back_args)


async def _channels_menu(pool, user, ui, args):
    clear_wait(user.max_user_id)
    if args == ["bg"]:
        state.CHANNEL_RETURN[user.max_user_id] = "bg:menu"
    await views.show_channels(pool, user, ui)


def _circle_mark(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as image:
        size = min(ImageOps.exif_transpose(image).size)
    return round_image(data, max(1, min(size, MAX_SIZE)))


async def _transform_template(pool, user, ui, args, transform) -> None:
    tid = _tid(args)
    item = await tpl_repo.get(pool, tid, user.id) if tid else None
    if not item:
        await views.show_templates(pool, user, ui)
        return
    await ui.show(views.PROCESSING_IMAGE, [])
    ui = Screen.for_user(user)
    src = Path(item.file_path)
    dest = src.with_suffix(".png")
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        result = await asyncio.to_thread(transform, src.read_bytes())
        await asyncio.to_thread(result.save, tmp, "PNG")
        tmp.replace(dest)
        if dest.resolve() != src.resolve():
            src.unlink(missing_ok=True)
            item = await tpl_repo.update(
                pool, item.id, user.id, file_path=str(dest)
            ) or replace(item, file_path=str(dest))
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        tmp.unlink(missing_ok=True)
    await views.show_template_card(pool, user, item, ui)


async def _round_template(pool, user, ui, args) -> None:
    await _transform_template(pool, user, ui, args, _circle_mark)


async def _bg_template(pool, user, ui, args) -> None:
    await _transform_template(pool, user, ui, args, remove_background)


ROUTES: dict[str, Handler] = {
    "nav:home": _tab(views.show_menu),
    "tab:tpl": _tab(views.show_templates),
    "tab:tails": _tab(views.show_tails),
    "tab:ch": _channels_menu,
    "tab:me": _tab(views.show_profile),
    "round:menu": _tab(rounding.show),
    "round:standard": rounding.standard,
    "round:custom": rounding.custom,
    "round:download": rounding.download,
    "bg:noop": _tab(background.show),
    "bg:menu": _tab(background.show),
    "bg:upload": background.upload,
    "bg:download": background.download,
    "tpl:new": _new_template,
    "tpl:back": _templates_back,
    "tpl:select": _select_template,
    "tpl:open": _open(tpl_repo, views.show_template_card, views.show_templates),
    "tpl:use": _use(
        tpl_repo.set_default,
        tpl_repo.get,
        views.show_template_card,
        views.show_templates,
    ),
    "tpl:del": _open(tpl_repo, views.show_delete_tpl, views.show_templates),
    "tpl:delok": _delok(tpl_repo.delete, views.show_templates),
    "tpl:round": _round_template,
    "tpl:bg": _bg_template,
    "wm:pos": _open(tpl_repo, views.show_position_picker, views.show_templates),
    "wm:w": _open(tpl_repo, views.show_width_picker, views.show_templates),
    "wm:op": _open(tpl_repo, views.show_opacity_picker, views.show_templates),
    "wm:rot": _open(tpl_repo, views.show_rotation_picker, views.show_templates),
    "wm:px": _open(tpl_repo, views.show_pad_picker, views.show_templates, "x"),
    "wm:py": _open(tpl_repo, views.show_pad_picker, views.show_templates, "y"),
    "wm:setpos": _tpl_field("position", _as_position, views.show_position_picker),
    "wm:setw": _tpl_field("width_pct", int, views.show_width_picker),
    "wm:setop": _tpl_field("opacity", int, views.show_opacity_picker),
    "wm:setrot": _tpl_field("rotation_deg", int, views.show_rotation_picker),
    "wm:setpx": _tpl_field("pad_x", int, views.show_pad_picker, ("x",)),
    "wm:setpy": _tpl_field("pad_y", int, views.show_pad_picker, ("y",)),
    "tail:off": _tail_off,
    "tail:new": _ask(WAIT_TAIL_VIDEO, views.ask_new_tail),
    "tail:open": _open(tails_repo, views.show_tail_card, views.show_tails),
    "tail:use": _use(
        tails_repo.set_default,
        tails_repo.get,
        views.show_tail_card,
        views.show_tails,
    ),
    "tail:place": _set(
        tails_repo.set_placement,
        views.show_tail_card,
        views.show_tails,
        str,
    ),
    "tail:del": _open(tails_repo, views.show_delete_tail, views.show_tails),
    "tail:delok": _delok(tails_repo.delete, views.show_tails),
    "ch:add": _ask(WAIT_CHANNEL_FORWARD, views.ask_bind_channel),
    "ch:open": _open(ch_repo, views.show_channel_card, views.show_channels),
    "ch:toggle": _toggle(
        ch_repo.get, _flip_enabled, views.show_channel_card, views.show_channels
    ),
    "ch:tpl": _set(
        _save_ch_tpl, views.show_channel_card, views.show_channels, int
    ),
    "ch:tail": _toggle(
        ch_repo.get, _flip_tail, views.show_channel_card, views.show_channels
    ),
    "ch:unbind": _delok(ch_repo.delete, views.show_channels),
}


async def handle_message_callback(pool: asyncpg.Pool, update: dict) -> None:
    user_id, callback_id, payload = parse_message_callback(update)
    if not user_id or not callback_id or not payload:
        return
    user = await user_repo.upsert_user(pool, int(user_id))
    key, args = parse_payload(str(payload))
    handler = ROUTES.get(key)
    if handler is None:
        await answer_callback(callback_id, notification="неизвестная кнопка")
        return
    await answer_callback(callback_id, "")
    ui = Screen.for_user(user, replace_mid=extract_message_mid(update))
    await handler(pool, user, ui, args)
    if key in {"nav:home", "tab:tails", "tab:ch", "tab:me"}:
        state.TEMPLATE_RETURN[user.max_user_id] = (key, [])
    elif key.startswith("round:"):
        state.TEMPLATE_RETURN[user.max_user_id] = ("round:menu", [])
    elif key.startswith("bg:"):
        state.TEMPLATE_RETURN[user.max_user_id] = ("bg:menu", [])
    elif key.startswith(("tail:", "ch:")):
        if key in {"tail:off", "tail:delok", "ch:unbind"}:
            destination = "tab:tails" if key.startswith("tail:") else "tab:ch"
            state.TEMPLATE_RETURN[user.max_user_id] = (destination, [])
        elif key in {"tail:new", "tail:del", "ch:add"}:
            state.TEMPLATE_RETURN[user.max_user_id] = (key, list(args))
        else:
            destination = "tail:open" if key.startswith("tail:") else "ch:open"
            state.TEMPLATE_RETURN[user.max_user_id] = (destination, list(args[:1]))
