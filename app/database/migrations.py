"""Idempotent startup DDL."""
from __future__ import annotations

import asyncpg

_DDL = """
CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL PRIMARY KEY,
    max_user_id   BIGINT NOT NULL UNIQUE,
    name          TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS templates (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    file_path     TEXT NOT NULL,
    position      TEXT NOT NULL DEFAULT 'se',
    width_pct     INT NOT NULL DEFAULT 30,
    opacity       INT NOT NULL DEFAULT 100,
    rotation_deg  INT NOT NULL DEFAULT 0,
    pad_x         INT NOT NULL DEFAULT 0,
    pad_y         INT NOT NULL DEFAULT 0,
    is_default    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_templates_user ON templates (user_id);

CREATE TABLE IF NOT EXISTS tails (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    file_path     TEXT NOT NULL,
    placement     TEXT NOT NULL DEFAULT 'end'
        CHECK (placement IN ('start', 'end')),
    is_default    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tails_user ON tails (user_id);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id         BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    tails_enabled   BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS channels (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chat_id       BIGINT NOT NULL UNIQUE,
    title         TEXT NOT NULL DEFAULT '',
    template_id   BIGINT REFERENCES templates(id) ON DELETE SET NULL,
    tail_id       BIGINT REFERENCES tails(id) ON DELETE SET NULL,
    use_tail      BOOLEAN NOT NULL DEFAULT FALSE,
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_channels_user ON channels (user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_templates_one_default
    ON templates (user_id) WHERE is_default;
CREATE UNIQUE INDEX IF NOT EXISTS idx_tails_one_default
    ON tails (user_id) WHERE is_default;

CREATE TABLE IF NOT EXISTS jobs (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL CHECK (kind IN ('photo', 'video')),
    status        TEXT NOT NULL DEFAULT 'ok',
    bytes_out     BIGINT NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_jobs_user_day ON jobs (user_id, created_at);

CREATE TABLE IF NOT EXISTS processed_mids (
    chat_id       BIGINT NOT NULL,
    mid           TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chat_id, mid)
);
"""


async def run_migrations(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_DDL)
        await conn.execute(
            "ALTER TABLE channels ADD COLUMN IF NOT EXISTS use_tail "
            "BOOLEAN NOT NULL DEFAULT FALSE"
        )
        await conn.execute("""
            ALTER TABLE templates ADD COLUMN IF NOT EXISTS slot INT;
            WITH numbered AS (
                SELECT id, row_number() OVER (PARTITION BY user_id ORDER BY id) AS slot
                FROM templates
            )
            UPDATE templates t SET slot = numbered.slot
            FROM numbered WHERE t.id = numbered.id AND t.slot IS NULL;
            ALTER TABLE templates ALTER COLUMN slot SET NOT NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_templates_user_slot
                ON templates (user_id, slot);
        """)
