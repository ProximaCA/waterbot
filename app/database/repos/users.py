from __future__ import annotations

from typing import Optional

import asyncpg

from app.models import User


async def upsert_user(pool: asyncpg.Pool, max_user_id: int, name: str = "") -> User:
    row = await pool.fetchrow(
        """
        INSERT INTO users (max_user_id, name)
        VALUES ($1, $2)
        ON CONFLICT (max_user_id) DO UPDATE
          SET name = CASE WHEN EXCLUDED.name <> '' THEN EXCLUDED.name ELSE users.name END
        RETURNING id, max_user_id, name
        """,
        max_user_id,
        name or "",
    )
    await pool.execute(
        """
        INSERT INTO user_settings (user_id, tails_enabled)
        VALUES ($1, FALSE)
        ON CONFLICT (user_id) DO NOTHING
        """,
        row["id"],
    )
    return User.from_row(row)


async def get_by_id(pool: asyncpg.Pool, user_id: int) -> Optional[User]:
    row = await pool.fetchrow(
        "SELECT id, max_user_id, name FROM users WHERE id = $1",
        user_id,
    )
    return User.from_row(row) if row else None
