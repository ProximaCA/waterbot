"""Postgres: promoting a lower id must not trip the partial unique index."""
from __future__ import annotations

import time

import asyncpg
import pytest

from app.config import DATABASE_URL
from app.database.migrations import run_migrations
from app.database.repos import tails as tails_repo
from app.database.repos import templates as tpl_repo
from app.database.repos import users as user_repo


@pytest.fixture
async def pool():
    try:
        p = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2, timeout=5)
    except OSError as exc:
        pytest.skip(f"postgres unreachable: {exc}")
    try:
        await run_migrations(p)
    except Exception as exc:
        await p.close()
        pytest.skip(f"migrations failed: {exc}")
    yield p
    await p.close()


async def _user(pool):
    uid = 8_000_000_000 + int(time.time() * 1000) % 1_000_000_000
    return await user_repo.upsert_user(pool, uid, "def")


async def test_template_set_default_promotes_lower_id(pool):
    user = await _user(pool)
    first = await tpl_repo.create(pool, user.id, name="A", file_path="/a.png")
    second = await tpl_repo.create(pool, user.id, name="B", file_path="/b.png")
    assert first.id < second.id
    assert first.is_default and not second.is_default

    await tpl_repo.set_default(pool, second.id, user.id)
    assert not (await tpl_repo.get(pool, first.id, user.id)).is_default
    assert (await tpl_repo.get(pool, second.id, user.id)).is_default

    await tpl_repo.set_default(pool, first.id, user.id)
    assert (await tpl_repo.get(pool, first.id, user.id)).is_default
    assert not (await tpl_repo.get(pool, second.id, user.id)).is_default

    await pool.execute("DELETE FROM users WHERE id = $1", user.id)


async def test_tail_set_default_promotes_lower_id(pool):
    user = await _user(pool)
    first = await tails_repo.create(pool, user.id, name="A", file_path="/a.mp4")
    second = await tails_repo.create(pool, user.id, name="B", file_path="/b.mp4")
    assert first.id < second.id
    assert first.is_default and not second.is_default

    await tails_repo.set_default(pool, second.id, user.id)
    assert not (await tails_repo.get(pool, first.id, user.id)).is_default
    assert (await tails_repo.get(pool, second.id, user.id)).is_default

    await tails_repo.set_default(pool, first.id, user.id)
    assert (await tails_repo.get(pool, first.id, user.id)).is_default
    assert not (await tails_repo.get(pool, second.id, user.id)).is_default

    await pool.execute("DELETE FROM users WHERE id = $1", user.id)


async def test_set_default_missing_id_keeps_current(pool):
    user = await _user(pool)
    first = await tpl_repo.create(pool, user.id, name="A", file_path="/a.png")
    await tpl_repo.set_default(pool, -1, user.id)
    assert (await tpl_repo.get(pool, first.id, user.id)).is_default
    await pool.execute("DELETE FROM users WHERE id = $1", user.id)


async def test_tail_set_default_missing_id_does_not_enable(pool):
    user = await _user(pool)
    first = await tails_repo.create(pool, user.id, name="A", file_path="/a.mp4")
    await tails_repo.set_tails_enabled(pool, user.id, False)
    await tails_repo.set_default(pool, -1, user.id)
    assert not await tails_repo.tails_enabled(pool, user.id)
    assert (await tails_repo.get(pool, first.id, user.id)).is_default
    await pool.execute("DELETE FROM users WHERE id = $1", user.id)
