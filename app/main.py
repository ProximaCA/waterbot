from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import aiohttp
from fastapi import FastAPI, Request

from app import state
from app.api.client import set_session, ssl_context
from app.api.max_api import get_me, set_my_commands, subscribe_bot_webhook
from app.config import (
    DATA_DIR,
    TOKEN,
    USE_WEBHOOK,
    WEBHOOK_PATH,
    WEBHOOK_PORT,
    WEBHOOK_URL,
)
from app.database.connection import close_pool, create_pool, get_pool
from app.database.migrations import run_migrations
from app.handlers.dispatch import dispatch
from app.polling import poll_updates_loop


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    pool = await create_pool()
    await run_migrations(pool)
    timeout = aiohttp.ClientTimeout(total=120)
    session = aiohttp.ClientSession(
        timeout=timeout,
        connector=aiohttp.TCPConnector(ssl=ssl_context()),
    )
    set_session(session)
    if not TOKEN:
        raise SystemExit("MAX_TOKEN is empty")
    me = await get_me()
    uid = me.get("user_id") if me else None
    if not uid:
        raise SystemExit("GET /me failed or no user_id")
    state.BOT_USER_ID = int(uid)
    state.BOT_USERNAME = str((me or {}).get("username") or "")
    print("BOT:", state.BOT_USERNAME, state.BOT_USER_ID)
    await set_my_commands()
    polling_task: asyncio.Task | None = None
    if USE_WEBHOOK:
        print("MODE: webhook")
        if WEBHOOK_URL:
            ok = await subscribe_bot_webhook(url=WEBHOOK_URL)
            print("webhook subscribe:", ok)
        else:
            print("WARNING: USE_WEBHOOK=true but WEBHOOK_URL is empty")
    else:
        print("MODE: polling")
        polling_task = asyncio.create_task(poll_updates_loop())
    try:
        yield
    finally:
        if polling_task:
            polling_task.cancel()
            try:
                await polling_task
            except asyncio.CancelledError:
                pass
        await session.close()
        set_session(None)
        await close_pool()


app = FastAPI(lifespan=lifespan, title="watermarkbot")


@app.get(WEBHOOK_PATH)
@app.get(WEBHOOK_PATH + "/")
async def health():
    return {"status": "alive"}


@app.post(WEBHOOK_PATH)
@app.post(WEBHOOK_PATH + "/")
async def max_webhook(request: Request):
    try:
        if not USE_WEBHOOK:
            return {"ok": True, "message": "webhook disabled"}
        update = await request.json()
        await dispatch(get_pool(), update)
    except Exception as exc:
        print("WEBHOOK ERROR:", repr(exc))
    return {"ok": True}


def run() -> None:
    import uvicorn

    if not TOKEN:
        raise SystemExit("MAX_TOKEN is empty")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=WEBHOOK_PORT,
        reload=False,
    )


if __name__ == "__main__":
    run()
