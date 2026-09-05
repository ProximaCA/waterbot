from __future__ import annotations

from pathlib import Path
from typing import Awaitable, Callable, Optional, Sequence

import asyncpg

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


def _open(get, card, listing) -> Handler:
    async def h(pool, user, ui, args):
        tid = _tid(args)
        item = await get(pool, tid, user.id) if tid else None
        if not item:
            await listing(pool, user, ui)
            return
        await card(pool, user, item, ui)

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


def _picker(fn, *extra) -> Handler:
    async def h(pool, user, ui, args):
        tid = _tid(args)
        if tid:
            await fn(ui, tid, *extra)

    return h


def _ask(kind, show) -> Handler:
    async def h(pool, user, ui, args):
        set_wait(user.max_user_id, kind)
        await show(user, ui)

    return h


def _set(save, card, listing, conv=str) -> Handler:
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
            await card(pool, user, item, ui)
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


def _tpl_field(field, conv) -> Handler:
    async def save(pool, tid, user_id, val):
        return await tpl_repo.update(pool, tid, user_id, **{field: val})

    return _set(save, views.show_template_card, views.show_templates, conv)


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


ROUTES: dict[str, Handler] = {
    "tab:tpl": _tab(views.show_templates),
    "tab:tails": _tab(views.show_tails),
    "tab:ch": _tab(views.show_channels),
    "tab:me": _tab(views.show_profile),
    "tpl:new": _ask(WAIT_WM_IMAGE, views.ask_new_template),
    "tpl:open": _open(tpl_repo.get, views.show_template_card, views.show_templates),
    "tpl:use": _use(
        tpl_repo.set_default,
        tpl_repo.get,
        views.show_template_card,
        views.show_templates,
    ),
    "tpl:del": _picker(views.show_delete_tpl),
    "tpl:delok": _delok(tpl_repo.delete, views.show_templates),
    "wm:pos": _picker(views.show_position_picker),
    "wm:w": _picker(views.show_width_picker),
    "wm:op": _picker(views.show_opacity_picker),
    "wm:rot": _picker(views.show_rotation_picker),
    "wm:px": _picker(views.show_pad_picker, "x"),
    "wm:py": _picker(views.show_pad_picker, "y"),
    "wm:setpos": _tpl_field("position", _as_position),
    "wm:setw": _tpl_field("width_pct", int),
    "wm:setop": _tpl_field("opacity", int),
    "wm:setrot": _tpl_field("rotation_deg", int),
    "wm:setpx": _tpl_field("pad_x", int),
    "wm:setpy": _tpl_field("pad_y", int),
    "tail:off": _tail_off,
    "tail:new": _ask(WAIT_TAIL_VIDEO, views.ask_new_tail),
    "tail:open": _open(tails_repo.get, views.show_tail_card, views.show_tails),
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
    "tail:del": _picker(views.show_delete_tail),
    "tail:delok": _delok(tails_repo.delete, views.show_tails),
    "ch:add": _ask(WAIT_CHANNEL_FORWARD, views.ask_bind_channel),
    "ch:open": _open(ch_repo.get, views.show_channel_card, views.show_channels),
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
