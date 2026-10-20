"""Default flags and owned deletion; only tails promote a replacement automatically."""
from __future__ import annotations

from typing import Literal, Optional

import asyncpg

Table = Literal["templates", "tails"]


async def set_default(
    conn: asyncpg.Connection, table: Table, user_id: int, row_id: int
) -> bool:
    found = await conn.fetchval(
        f"SELECT 1 FROM {table} WHERE id = $1 AND user_id = $2",
        row_id,
        user_id,
    )
    if not found:
        return False
    await conn.execute(
        f"UPDATE {table} SET is_default = FALSE WHERE user_id = $1", user_id
    )
    await conn.execute(
        f"UPDATE {table} SET is_default = TRUE WHERE id = $1 AND user_id = $2",
        row_id,
        user_id,
    )
    return True


async def delete_owned(
    conn: asyncpg.Connection, table: Table, user_id: int, row_id: int
) -> Optional[asyncpg.Record]:
    row = await conn.fetchrow(
        f"""
        DELETE FROM {table}
        WHERE id = $1 AND user_id = $2
        RETURNING file_path, is_default
        """,
        row_id,
        user_id,
    )
    if not row:
        return None
    if table == "tails" and row["is_default"]:
        nxt = await conn.fetchval(
            f"SELECT id FROM {table} WHERE user_id = $1 ORDER BY id LIMIT 1",
            user_id,
        )
        if nxt:
            await conn.execute(
                f"UPDATE {table} SET is_default = TRUE WHERE id = $1", nxt
            )
    return row
