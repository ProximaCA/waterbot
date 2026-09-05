from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.handlers import pipeline
from app.models import Template, User

_USER = User(id=1, max_user_id=50, name="n")
_TPL = Template(id=3, user_id=1, name="t", file_path="p.png")


async def test_send_result_dm_caption(tmp_path: Path):
    dest = tmp_path / "out.jpg"
    dest.write_bytes(b"x")
    send = AsyncMock(return_value={"message": {"body": {"mid": "out"}}})
    with patch.object(pipeline.max_api, "send_file", send):
        r = await pipeline._send_result(dest, "photo", _USER, None)
    assert r is not None
    kwargs = send.await_args.kwargs
    assert kwargs["caption"] == "Готово"
    assert kwargs["user_id"] == 50
    assert kwargs["chat_id"] is None


async def test_send_result_channel_empty_caption(tmp_path: Path):
    dest = tmp_path / "out.jpg"
    dest.write_bytes(b"x")
    send = AsyncMock(return_value={"message": {"body": {"mid": "out-9"}}})
    with patch.object(pipeline.max_api, "send_file", send):
        r = await pipeline._send_result(dest, "photo", _USER, 99)
    kwargs = send.await_args.kwargs
    assert kwargs["caption"] == ""
    assert kwargs["user_id"] is None
    assert kwargs["chat_id"] == 99
    assert r == send.return_value


async def test_process_media_returns_send_if_record_fails(tmp_path: Path):
    dest = tmp_path / "out.jpg"
    dest.write_bytes(b"x")
    send = AsyncMock(return_value={"message": {"body": {"mid": "out"}}})
    record = AsyncMock(side_effect=RuntimeError("db"))
    with (
        patch.object(pipeline.max_api, "send_file", send),
        patch.object(pipeline.jobs_repo, "record", record),
        patch.object(pipeline, "apply_photo", lambda *a, **k: dest),
        patch.object(pipeline, "tmp_path", lambda *_a, **_k: dest),
    ):
        r = await pipeline.process_media(
            object(), _USER, b"xx", kind="photo", template=_TPL
        )
    assert r == send.return_value


async def test_process_media_dm_notifies_when_send_returns_none(tmp_path: Path):
    dest = tmp_path / "out.jpg"
    dest.write_bytes(b"x")
    notify = AsyncMock()
    with (
        patch.object(pipeline.max_api, "send_file", AsyncMock(return_value=None)),
        patch.object(pipeline.jobs_repo, "record", AsyncMock()),
        patch.object(pipeline.max_api, "send_to_user", notify),
        patch.object(pipeline, "apply_photo", lambda *a, **k: dest),
        patch.object(pipeline, "tmp_path", lambda *_a, **_k: dest),
    ):
        r = await pipeline.process_media(
            object(), _USER, b"xx", kind="photo", template=_TPL
        )
    assert r is None
    notify.assert_awaited()
    assert notify.await_args.args[1] == "Не получилось обработать фото."


async def test_resolve_template_missing_pin_is_none():
    get = AsyncMock(return_value=None)
    default = AsyncMock(return_value=_TPL)
    with (
        patch.object(pipeline.tpl_repo, "get", get),
        patch.object(pipeline.tpl_repo, "get_default", default),
    ):
        r = await pipeline.resolve_template(object(), 1, 99)
    assert r is None
    default.assert_not_awaited()
    get.assert_awaited_once()
