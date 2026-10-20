from __future__ import annotations

import asyncpg

from app.database.repos import users as user_repo
from app.handlers import background, rounding
from app.renderers import views
from app.renderers.views import Screen
from app.schemas.updates import parse_bot_started
from app.wait import clear_wait


async def handle_bot_started(pool: asyncpg.Pool, update: dict) -> None:
    user_id, _payload, _chat = parse_bot_started(update)
    if not user_id:
        return
    user = await user_repo.upsert_user(pool, int(user_id), "")
    clear_wait(int(user_id))
    background.reset_download(user)
    rounding.reset_download(user)
    await views.show_menu(pool, user, Screen.for_user(user))
