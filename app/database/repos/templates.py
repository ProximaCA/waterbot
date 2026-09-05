from __future__ import annotations

from typing import Any, Optional

import asyncpg

from app.database.repos import owned
from app.models import Template

_COLS = (
    "id, user_id, name, file_path, position, width_pct, opacity, "
    "rotation_deg, pad_x, pad_y, is_default, created_at"
)
_ALLOWED = frozenset(
    {"name", "position", "width_pct", "opacity", "rotation_deg", "pad_x", "pad_y"}
)


def _one(row) -> Optional[Template]:
    return Template.from_row(row) if row else None


async def list_for(pool: asyncpg.Pool, user_id: int) -> list[Template]:
    rows = await pool.fetch(
        f"SELECT {_COLS} FROM templates WHERE user_id = $1 ORDER BY id",
        user_id,
    )
    return [Template.from_row(r) for r in rows]


async def get(pool: asyncpg.Pool, template_id: int, user_id: int) -> Optional[Template]:
    row = await pool.fetchrow(
        f"SELECT {_COLS} FROM templates WHERE id = $1 AND user_id = $2",
        template_id,
        user_id,
    )
    return _one(row)


async def get_default(pool: asyncpg.Pool, user_id: int) -> Optional[Template]:
    row = await pool.fetchrow(
        f"""
        SELECT {_COLS} FROM templates
        WHERE user_id = $1 AND is_default
        ORDER BY id LIMIT 1
        """,
        user_id,
    )
    return _one(row)


async def create(
    pool: asyncpg.Pool, user_id: int, *, name: str, file_path: str
) -> Template:
    async with pool.acquire() as conn:
        async with conn.transaction():
            n = await conn.fetchval(
                "SELECT COUNT(*) FROM templates WHERE user_id = $1", user_id
            )
            make_default = int(n or 0) == 0
            row = await conn.fetchrow(
                f"""
                INSERT INTO templates (user_id, name, file_path, is_default)
                VALUES ($1, $2, $3, $4)
                RETURNING {_COLS}
                """,
                user_id,
                name,
                file_path,
                make_default,
            )
    return Template.from_row(row)


async def update(
    pool: asyncpg.Pool, template_id: int, user_id: int, **fields: Any
) -> Optional[Template]:
    sets = []
    args: list[Any] = []
    for key, val in fields.items():
        if key not in _ALLOWED:
            raise ValueError(f"unknown template field {key}")
        args.append(val)
        sets.append(f"{key} = ${len(args)}")
    if not sets:
        return await get(pool, template_id, user_id)
    args.extend([template_id, user_id])
    row = await pool.fetchrow(
        f"""
        UPDATE templates SET {", ".join(sets)}
        WHERE id = ${len(args) - 1} AND user_id = ${len(args)}
        RETURNING {_COLS}
        """,
        *args,
    )
    return _one(row)


async def set_default(pool: asyncpg.Pool, template_id: int, user_id: int) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            await owned.set_default(conn, "templates", user_id, template_id)


async def delete(pool: asyncpg.Pool, template_id: int, user_id: int) -> Optional[str]:
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await owned.delete_owned(conn, "templates", user_id, template_id)
            return str(row["file_path"]) if row else None
