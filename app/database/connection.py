"""Single asyncpg pool. No RLS — one bot, one database."""
from __future__ import annotations

import asyncpg

from app.config import DATABASE_URL

_pool: asyncpg.Pool | None = None


async def create_pool() -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=8)
    return _pool


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("database pool is not initialised")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
