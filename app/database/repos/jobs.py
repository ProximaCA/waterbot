from __future__ import annotations

import asyncpg

from app.models import DayStats


async def record(
    pool: asyncpg.Pool, user_id: int, kind: str, *, bytes_out: int, status: str = "ok"
) -> None:
    await pool.execute(
        """
        INSERT INTO jobs (user_id, kind, status, bytes_out)
        VALUES ($1, $2, $3, $4)
        """,
        user_id,
        kind,
        status,
        int(bytes_out),
    )


async def today_stats(pool: asyncpg.Pool, user_id: int) -> DayStats:
    row = await pool.fetchrow(
        """
        SELECT
          COALESCE(SUM(CASE WHEN kind = 'photo' THEN 1 ELSE 0 END), 0) AS photos,
          COALESCE(SUM(CASE WHEN kind = 'video' THEN 1 ELSE 0 END), 0) AS videos,
          COALESCE(SUM(bytes_out), 0) AS bytes_out
        FROM jobs
        WHERE user_id = $1
          AND created_at >= date_trunc('day', now())
          AND status = 'ok'
        """,
        user_id,
    )
    return DayStats(
        photos=int(row["photos"]),
        videos=int(row["videos"]),
        bytes_out=int(row["bytes_out"]),
    )
