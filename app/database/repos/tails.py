from __future__ import annotations

from typing import Optional

import asyncpg

from app.database.repos import owned
from app.models import Tail

_COLS = "id, user_id, name, file_path, placement, is_default, created_at"
_ENABLE = """
INSERT INTO user_settings (user_id, tails_enabled)
VALUES ($1, TRUE)
ON CONFLICT (user_id) DO UPDATE SET tails_enabled = TRUE
"""


def _one(row) -> Optional[Tail]:
    return Tail.from_row(row) if row else None


async def list_for(pool: asyncpg.Pool, user_id: int) -> list[Tail]:
    rows = await pool.fetch(
        f"SELECT {_COLS} FROM tails WHERE user_id = $1 ORDER BY id", user_id
    )
    return [Tail.from_row(r) for r in rows]


async def get(pool: asyncpg.Pool, tail_id: int, user_id: int) -> Optional[Tail]:
    row = await pool.fetchrow(
        f"SELECT {_COLS} FROM tails WHERE id = $1 AND user_id = $2",
        tail_id,
        user_id,
    )
    return _one(row)


async def get_default(pool: asyncpg.Pool, user_id: int) -> Optional[Tail]:
    row = await pool.fetchrow(
        f"""
        SELECT {_COLS} FROM tails
        WHERE user_id = $1 AND is_default
        ORDER BY id LIMIT 1
        """,
        user_id,
    )
    return _one(row)


async def tails_enabled(pool: asyncpg.Pool, user_id: int) -> bool:
    val = await pool.fetchval(
        "SELECT tails_enabled FROM user_settings WHERE user_id = $1",
        user_id,
    )
    return bool(val)


async def set_tails_enabled(pool: asyncpg.Pool, user_id: int, enabled: bool) -> None:
    await pool.execute(
        """
        INSERT INTO user_settings (user_id, tails_enabled)
        VALUES ($1, $2)
        ON CONFLICT (user_id) DO UPDATE SET tails_enabled = EXCLUDED.tails_enabled
        """,
        user_id,
        enabled,
    )


async def create(
    pool: asyncpg.Pool, user_id: int, *, name: str, file_path: str
) -> Tail:
    async with pool.acquire() as conn:
        async with conn.transaction():
            n = await conn.fetchval(
                "SELECT COUNT(*) FROM tails WHERE user_id = $1", user_id
            )
            make_default = int(n or 0) == 0
            row = await conn.fetchrow(
                f"""
                INSERT INTO tails (user_id, name, file_path, is_default)
                VALUES ($1, $2, $3, $4)
                RETURNING {_COLS}
                """,
                user_id,
                name,
                file_path,
                make_default,
            )
            if make_default:
                await conn.execute(_ENABLE, user_id)
    return Tail.from_row(row)


async def set_placement(
    pool: asyncpg.Pool, tail_id: int, user_id: int, placement: str
) -> Optional[Tail]:
    if placement not in ("start", "end"):
        return await get(pool, tail_id, user_id)
    row = await pool.fetchrow(
        f"""
        UPDATE tails SET placement = $3
        WHERE id = $1 AND user_id = $2
        RETURNING {_COLS}
        """,
        tail_id,
        user_id,
        placement,
    )
    return _one(row)


async def set_default(pool: asyncpg.Pool, tail_id: int, user_id: int) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            if await owned.set_default(conn, "tails", user_id, tail_id):
                await conn.execute(_ENABLE, user_id)


async def delete(pool: asyncpg.Pool, tail_id: int, user_id: int) -> Optional[str]:
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await owned.delete_owned(conn, "tails", user_id, tail_id)
            if row is None:
                return None
            left = await conn.fetchval(
                "SELECT COUNT(*) FROM tails WHERE user_id = $1", user_id
            )
            if int(left or 0) == 0:
                await conn.execute(
                    "UPDATE user_settings SET tails_enabled = FALSE WHERE user_id = $1",
                    user_id,
                )
            return str(row["file_path"])
