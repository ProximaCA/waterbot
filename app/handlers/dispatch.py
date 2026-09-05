from __future__ import annotations

import asyncpg

from app.handlers.bot_started import handle_bot_started
from app.handlers.message_callback import handle_message_callback
from app.handlers.message_created import handle_message_created


async def dispatch(pool: asyncpg.Pool, update: dict) -> None:
    utype = update.get("update_type")
    if utype == "bot_started":
        await handle_bot_started(pool, update)
    elif utype == "message_callback":
        await handle_message_callback(pool, update)
    elif utype == "message_created":
        await handle_message_created(pool, update)
