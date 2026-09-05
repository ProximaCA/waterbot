from __future__ import annotations

from typing import Optional

import asyncpg

from app.models import Channel

_COLS = (
    "id, user_id, chat_id, title, template_id, use_tail, enabled, created_at"
)


def _one(row) -> Optional[Channel]:
    return Channel.from_row(row) if row else None


async def list_for(pool: asyncpg.Pool, user_id: int) -> list[Channel]:
    rows = await pool.fetch(
        f"SELECT {_COLS} FROM channels WHERE user_id = $1 ORDER BY id", user_id
    )
    return [Channel.from_row(r) for r in rows]


async def get(pool: asyncpg.Pool, channel_pk: int, user_id: int) -> Optional[Channel]:
    row = await pool.fetchrow(
        f"SELECT {_COLS} FROM channels WHERE id = $1 AND user_id = $2",
        channel_pk,
        user_id,
    )
    return _one(row)


async def get_by_chat(pool: asyncpg.Pool, chat_id: int) -> Optional[Channel]:
    row = await pool.fetchrow(
        f"SELECT {_COLS} FROM channels WHERE chat_id = $1", chat_id
    )
    return _one(row)


async def upsert(
    pool: asyncpg.Pool, user_id: int, chat_id: int, title: str
) -> Optional[Channel]:
    row = await pool.fetchrow(
        f"""
        INSERT INTO channels (user_id, chat_id, title)
        VALUES ($1, $2, $3)
        ON CONFLICT (chat_id) DO UPDATE
          SET title = EXCLUDED.title
        WHERE channels.user_id = EXCLUDED.user_id
        RETURNING {_COLS}
        """,
        user_id,
        chat_id,
        title or "",
    )
    return Channel.from_row(row) if row else None


async def set_enabled(
    pool: asyncpg.Pool, channel_pk: int, user_id: int, enabled: bool
) -> Optional[Channel]:
    row = await pool.fetchrow(
        f"""
        UPDATE channels SET enabled = $3
        WHERE id = $1 AND user_id = $2
        RETURNING {_COLS}
        """,
        channel_pk,
        user_id,
        enabled,
    )
    return _one(row)


async def set_use_tail(
    pool: asyncpg.Pool, channel_pk: int, user_id: int, use_tail: bool
) -> Optional[Channel]:
    row = await pool.fetchrow(
        f"""
        UPDATE channels SET use_tail = $3
        WHERE id = $1 AND user_id = $2
        RETURNING {_COLS}
        """,
        channel_pk,
        user_id,
        use_tail,
    )
    return _one(row)


async def set_template(
    pool: asyncpg.Pool, channel_pk: int, user_id: int, template_id: Optional[int]
) -> Optional[Channel]:
    row = await pool.fetchrow(
        f"""
        UPDATE channels SET template_id = $3
        WHERE id = $1 AND user_id = $2
        RETURNING {_COLS}
        """,
        channel_pk,
        user_id,
        template_id,
    )
    return _one(row)


async def delete(pool: asyncpg.Pool, channel_pk: int, user_id: int) -> Optional[str]:
    await pool.execute(
        "DELETE FROM channels WHERE id = $1 AND user_id = $2",
        channel_pk,
        user_id,
    )
    return None


async def mark_processed(pool: asyncpg.Pool, chat_id: int, mid: str) -> bool:
    """Claim this mid. True if inserted (new)."""
    tag = await pool.execute(
        """
        INSERT INTO processed_mids (chat_id, mid)
        VALUES ($1, $2)
        ON CONFLICT DO NOTHING
        """,
        chat_id,
        mid,
    )
    return tag.endswith("1")


async def unmark_processed(pool: asyncpg.Pool, chat_id: int, mid: str) -> None:
    await pool.execute(
        "DELETE FROM processed_mids WHERE chat_id = $1 AND mid = $2",
        chat_id,
        mid,
    )
