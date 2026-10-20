from __future__ import annotations

from typing import Any, Optional

import asyncpg

from app.database.repos import owned
from app.models import Template

_COLS = (
    "id, user_id, name, file_path, position, width_pct, opacity, "
    "rotation_deg, pad_x, pad_y, is_default, created_at, slot"
)
_ALLOWED = frozenset(
    {"name", "file_path", "position", "width_pct", "opacity", "rotation_deg", "pad_x", "pad_y"}
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
    pool: asyncpg.Pool, user_id: int, *, name: str, file_path: str,
    slot: Optional[int] = None,
) -> Template:
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.fetchval("SELECT id FROM users WHERE id = $1 FOR UPDATE", user_id)
            rows = await conn.fetch(
                "SELECT slot FROM templates WHERE user_id = $1", user_id
            )
            occupied = {r["slot"] for r in rows}
            if slot is None:
                slot = next((s for s in range(1, 4) if s not in occupied), None)
            if slot not in (1, 2, 3) or slot in occupied:
                raise ValueError("template slot unavailable")
            row = await conn.fetchrow(
                f"""
                INSERT INTO templates (user_id, name, file_path, is_default, slot)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING {_COLS}
                """,
                user_id,
                name,
                file_path,
                False,
                slot,
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
