"""Postgres: promoting a lower id must not trip the partial unique index."""
from __future__ import annotations

import time
import asyncio
import uuid

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
    assert not first.is_default and not second.is_default
    assert await tpl_repo.get_default(pool, user.id) is None

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
    await tpl_repo.set_default(pool, first.id, user.id)
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


async def test_template_slots_survive_deletion_and_reject_overwrite(pool):
    user = await _user(pool)
    try:
        third = await tpl_repo.create(pool, user.id, name="third", file_path="/3.png", slot=3)
        first = await tpl_repo.create(pool, user.id, name="first", file_path="/1.png", slot=1)
        assert not third.is_default and third.slot == 3
        assert sorted(t.slot for t in await tpl_repo.list_for(pool, user.id)) == [1, 3]
        with pytest.raises(ValueError):
            await tpl_repo.create(pool, user.id, name="overwrite", file_path="/x.png", slot=3)
        await tpl_repo.delete(pool, first.id, user.id)
        assert (await tpl_repo.get(pool, third.id, user.id)).slot == 3
        replacement = await tpl_repo.create(pool, user.id, name="new", file_path="/new.png")
        assert replacement.slot == 1
        await tpl_repo.create(pool, user.id, name="second", file_path="/2.png", slot=2)
        with pytest.raises(ValueError):
            await tpl_repo.create(pool, user.id, name="fourth", file_path="/4.png")
        with pytest.raises(ValueError):
            await tpl_repo.create(pool, user.id, name="invalid", file_path="/0.png", slot=0)
    finally:
        await pool.execute("DELETE FROM users WHERE id = $1", user.id)


@pytest.mark.parametrize("repo,promote", [(tpl_repo, False), (tails_repo, True)])
async def test_delete_active_only_promotes_tails(pool, repo, promote):
    user = await _user(pool)
    try:
        first = await repo.create(pool, user.id, name="A", file_path="/a.png")
        second = await repo.create(pool, user.id, name="B", file_path="/b.png")
        await repo.set_default(pool, first.id, user.id)
        await repo.delete(pool, first.id, user.id)
        assert (await repo.get(pool, second.id, user.id)).is_default is promote
        if not promote:
            assert await repo.get_default(pool, user.id) is None
    finally:
        await pool.execute("DELETE FROM users WHERE id = $1", user.id)


async def test_concurrent_slot_upload_keeps_one_template(pool):
    user = await _user(pool)
    try:
        results = await asyncio.gather(*(
            tpl_repo.create(pool, user.id, name=f"upload-{i}", file_path=f"/{i}.png", slot=3)
            for i in range(2)
        ), return_exceptions=True)
        assert sum(isinstance(r, ValueError) for r in results) == 1
        templates = await tpl_repo.list_for(pool, user.id)
        assert len(templates) == 1 and templates[0].slot == 3
    finally:
        await pool.execute("DELETE FROM users WHERE id = $1", user.id)


async def test_slot_migration_preserves_legacy_templates(pool):
    from app.database.migrations import _DDL

    schema = "ui_test_" + uuid.uuid4().hex
    await pool.execute(f'CREATE SCHEMA "{schema}"')
    legacy = await asyncpg.create_pool(
        DATABASE_URL, min_size=1, max_size=1, server_settings={"search_path": schema}
    )
    try:
        await legacy.execute(_DDL)
        user = await _user(legacy)
        await legacy.execute("""
            INSERT INTO templates (user_id, name, file_path, is_default)
            SELECT $1, 'legacy-' || n, '/' || n || '.png', n = 4
            FROM generate_series(1, 4) AS n
        """, user.id)
        before = await legacy.fetch("SELECT id, name, file_path, is_default FROM templates ORDER BY id")
        await run_migrations(legacy)
        await run_migrations(legacy)
        after = await legacy.fetch("SELECT id, name, file_path, is_default FROM templates ORDER BY id")
        assert before == after
        assert [t.slot for t in await tpl_repo.list_for(legacy, user.id)] == [1, 2, 3, 4]
    finally:
        await legacy.close()
        await pool.execute(f'DROP SCHEMA "{schema}" CASCADE')
