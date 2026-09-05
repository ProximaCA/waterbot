from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

from app.handlers import channel as ch
from app.models import Channel, Tail, Template, User

_UPD = {
    "update_type": "message_created",
    "message": {
        "recipient": {"chat_id": 99, "chat_type": "channel"},
        "body": {
            "mid": "mid-1",
            "attachments": [{"type": "image", "payload": {"token": "t"}}],
        },
    },
}
_CH = Channel(id=1, user_id=7, chat_id=99, title="c", enabled=True, template_id=3)
_USER = User(id=7, max_user_id=100, name="n")
_TPL = Template(id=3, user_id=7, name="t", file_path="p.png")


def _run(*, claimed: bool, process_ok: bool, mark, unmark, delete, process):
    stack = ExitStack()
    stack.enter_context(patch.object(ch.ch_repo, "get_by_chat", AsyncMock(return_value=_CH)))
    stack.enter_context(patch.object(ch.ch_repo, "mark_processed", mark))
    mark.return_value = claimed
    stack.enter_context(patch.object(ch.ch_repo, "unmark_processed", unmark))
    stack.enter_context(patch.object(ch.user_repo, "get_by_id", AsyncMock(return_value=_USER)))
    stack.enter_context(
        patch.object(ch.pipeline, "resolve_template", AsyncMock(return_value=_TPL))
    )
    stack.enter_context(
        patch.object(ch.pipeline, "fetch_image", AsyncMock(return_value=b"\xff\xd8\xffxx"))
    )
    stack.enter_context(patch.object(ch.pipeline, "process_media", process))
    process.return_value = (
        {"message": {"body": {"mid": "out-1"}}} if process_ok else None
    )
    stack.enter_context(patch.object(ch.max_api, "delete_message", delete))
    delete.return_value = True
    return stack


async def test_channel_claims_then_deletes_on_success():
    mark, unmark, delete, process = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    with _run(claimed=True, process_ok=True, mark=mark, unmark=unmark, delete=delete, process=process):
        await ch.handle_channel_post(object(), _UPD)
    assert [c.args[1:] for c in mark.await_args_list] == [
        (99, "mid-1"),
        (99, "out-1"),
    ]
    process.assert_awaited_once()
    assert process.await_args.kwargs["chat_id"] == 99
    delete.assert_awaited_once_with("mid-1")
    unmark.assert_not_awaited()


async def test_channel_unclaims_when_send_fails():
    mark, unmark, delete, process = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    with _run(claimed=True, process_ok=False, mark=mark, unmark=unmark, delete=delete, process=process):
        await ch.handle_channel_post(object(), _UPD)
    unmark.assert_awaited_once()
    delete.assert_not_awaited()


async def test_channel_skips_if_already_claimed():
    mark, unmark, delete, process = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    with _run(claimed=False, process_ok=True, mark=mark, unmark=unmark, delete=delete, process=process):
        await ch.handle_channel_post(object(), _UPD)
    process.assert_not_awaited()
    delete.assert_not_awaited()


async def test_channel_file_image_is_processed():
    mark, unmark, delete, process = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    upd = {
        "update_type": "message_created",
        "message": {
            "recipient": {"chat_id": 99, "chat_type": "channel"},
            "body": {
                "mid": "mid-f",
                "attachments": [
                    {
                        "type": "file",
                        "payload": {"token": "f1", "filename": "shot.png"},
                    }
                ],
            },
        },
    }
    with _run(
        claimed=True,
        process_ok=True,
        mark=mark,
        unmark=unmark,
        delete=delete,
        process=process,
    ):
        await ch.handle_channel_post(object(), upd)
    process.assert_awaited_once()
    delete.assert_awaited_once_with("mid-f")


async def test_channel_skips_round_video():
    mark = AsyncMock()
    upd = {
        "update_type": "message_created",
        "message": {
            "recipient": {"chat_id": 99, "chat_type": "channel"},
            "body": {
                "mid": "mid-r",
                "attachments": [
                    {"type": "video", "payload": {"token": "t", "is_round": True}}
                ],
            },
        },
    }
    with (
        patch.object(ch.ch_repo, "get_by_chat", AsyncMock(return_value=_CH)),
        patch.object(ch.ch_repo, "mark_processed", mark),
    ):
        await ch.handle_channel_post(object(), upd)
    mark.assert_not_awaited()


async def test_channel_keeps_claim_when_delete_raises():
    mark, unmark, delete, process = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    with _run(
        claimed=True,
        process_ok=True,
        mark=mark,
        unmark=unmark,
        delete=delete,
        process=process,
    ):
        delete.side_effect = TimeoutError("net")
        await ch.handle_channel_post(object(), _UPD)
    unmark.assert_not_awaited()
    process.assert_awaited_once()


async def test_channel_deletes_even_if_outgoing_mark_fails():
    mark, unmark, delete, process = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    with _run(
        claimed=True,
        process_ok=True,
        mark=mark,
        unmark=unmark,
        delete=delete,
        process=process,
    ):
        mark.side_effect = [True, RuntimeError("db")]
        await ch.handle_channel_post(object(), _UPD)
    delete.assert_awaited_once_with("mid-1")
    unmark.assert_not_awaited()


async def test_channel_album_processes_each_then_deletes():
    mark, unmark, delete, process = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    upd = {
        "update_type": "message_created",
        "message": {
            "recipient": {"chat_id": 99, "chat_type": "channel"},
            "body": {
                "mid": "mid-al",
                "attachments": [
                    {"type": "image", "payload": {"token": "a"}},
                    {"type": "image", "payload": {"token": "b"}},
                ],
            },
        },
    }
    with _run(
        claimed=True,
        process_ok=True,
        mark=mark,
        unmark=unmark,
        delete=delete,
        process=process,
    ):
        process.side_effect = [
            {"message": {"body": {"mid": "out-a"}}},
            {"message": {"body": {"mid": "out-b"}}},
        ]
        await ch.handle_channel_post(object(), upd)
    assert process.await_count == 2
    delete.assert_awaited_once_with("mid-al")
    assert [c.args[1:] for c in mark.await_args_list] == [
        (99, "mid-al"),
        (99, "out-a"),
        (99, "out-b"),
    ]
    unmark.assert_not_awaited()


async def test_channel_mixed_photo_video_processes_both():
    mark, unmark, delete, process = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    upd = {
        "update_type": "message_created",
        "message": {
            "recipient": {"chat_id": 99, "chat_type": "channel"},
            "body": {
                "mid": "mid-mx",
                "attachments": [
                    {"type": "video", "payload": {"token": "vid"}},
                    {"type": "image", "payload": {"token": "pic"}},
                ],
            },
        },
    }
    with (
        _run(
            claimed=True,
            process_ok=True,
            mark=mark,
            unmark=unmark,
            delete=delete,
            process=process,
        ),
        patch.object(
            ch.max_api, "download_payload", AsyncMock(return_value=b"mp4bytes")
        ),
    ):
        process.side_effect = [
            {"message": {"body": {"mid": "out-v"}}},
            {"message": {"body": {"mid": "out-p"}}},
        ]
        await ch.handle_channel_post(object(), upd)
    assert [c.kwargs["kind"] for c in process.await_args_list] == ["video", "photo"]
    delete.assert_awaited_once_with("mid-mx")
    unmark.assert_not_awaited()


async def test_channel_album_keeps_claim_if_later_item_raises():
    mark, unmark, delete, process = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    upd = {
        "update_type": "message_created",
        "message": {
            "recipient": {"chat_id": 99, "chat_type": "channel"},
            "body": {
                "mid": "mid-al",
                "attachments": [
                    {"type": "image", "payload": {"token": "a"}},
                    {"type": "image", "payload": {"token": "b"}},
                ],
            },
        },
    }
    with _run(
        claimed=True,
        process_ok=True,
        mark=mark,
        unmark=unmark,
        delete=delete,
        process=process,
    ):
        process.side_effect = [
            {"message": {"body": {"mid": "out-a"}}},
            RuntimeError("db"),
        ]
        await ch.handle_channel_post(object(), upd)
    assert process.await_count == 2
    delete.assert_not_awaited()
    unmark.assert_not_awaited()


async def test_channel_album_keeps_original_if_one_send_fails():
    mark, unmark, delete, process = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    upd = {
        "update_type": "message_created",
        "message": {
            "recipient": {"chat_id": 99, "chat_type": "channel"},
            "body": {
                "mid": "mid-al",
                "attachments": [
                    {"type": "image", "payload": {"token": "a"}},
                    {"type": "image", "payload": {"token": "b"}},
                ],
            },
        },
    }
    with _run(
        claimed=True,
        process_ok=True,
        mark=mark,
        unmark=unmark,
        delete=delete,
        process=process,
    ):
        process.side_effect = [
            {"message": {"body": {"mid": "out-a"}}},
            None,
        ]
        await ch.handle_channel_post(object(), upd)
    assert process.await_count == 2
    delete.assert_not_awaited()
    unmark.assert_not_awaited()


async def test_channel_video_uses_channel_tail_not_resolve_tail():
    mark, unmark, delete, process = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    ch_on = Channel(
        id=1, user_id=7, chat_id=99, title="c", enabled=True, template_id=3, use_tail=True
    )
    tail = Tail(id=9, user_id=7, name="h", file_path="h.mp4")
    upd = {
        "update_type": "message_created",
        "message": {
            "recipient": {"chat_id": 99, "chat_type": "channel"},
            "body": {
                "mid": "mid-v",
                "attachments": [{"type": "video", "payload": {"token": "vid"}}],
            },
        },
    }
    get_default = AsyncMock(return_value=tail)
    resolve_tail = AsyncMock()
    with (
        _run(
            claimed=True,
            process_ok=True,
            mark=mark,
            unmark=unmark,
            delete=delete,
            process=process,
        ),
        patch.object(ch.ch_repo, "get_by_chat", AsyncMock(return_value=ch_on)),
        patch.object(ch.tails_repo, "get_default", get_default),
        patch.object(ch.pipeline, "resolve_tail", resolve_tail),
        patch.object(ch.max_api, "download_payload", AsyncMock(return_value=b"mp4")),
    ):
        await ch.handle_channel_post(object(), upd)
    get_default.assert_awaited_once()
    resolve_tail.assert_not_awaited()
    assert process.await_args.kwargs["tail"] is tail
    assert process.await_args.kwargs["chat_id"] == 99
    assert process.await_args.kwargs["kind"] == "video"


async def test_channel_video_skips_tail_when_use_tail_off():
    mark, unmark, delete, process = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    get_default = AsyncMock()
    resolve_tail = AsyncMock()
    upd = {
        "update_type": "message_created",
        "message": {
            "recipient": {"chat_id": 99, "chat_type": "channel"},
            "body": {
                "mid": "mid-v",
                "attachments": [{"type": "video", "payload": {"token": "vid"}}],
            },
        },
    }
    with (
        _run(
            claimed=True,
            process_ok=True,
            mark=mark,
            unmark=unmark,
            delete=delete,
            process=process,
        ),
        patch.object(ch.tails_repo, "get_default", get_default),
        patch.object(ch.pipeline, "resolve_tail", resolve_tail),
        patch.object(ch.max_api, "download_payload", AsyncMock(return_value=b"mp4")),
    ):
        await ch.handle_channel_post(object(), upd)
    get_default.assert_not_awaited()
    resolve_tail.assert_not_awaited()
    assert process.await_args.kwargs["tail"] is None
    assert process.await_args.kwargs["chat_id"] == 99


async def test_channel_album_fetch_miss_then_success_keeps_original():
    mark, unmark, delete, process = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    upd = {
        "update_type": "message_created",
        "message": {
            "recipient": {"chat_id": 99, "chat_type": "channel"},
            "body": {
                "mid": "mid-al",
                "attachments": [
                    {"type": "image", "payload": {"token": "a"}},
                    {"type": "image", "payload": {"token": "b"}},
                ],
            },
        },
    }
    with (
        _run(
            claimed=True,
            process_ok=True,
            mark=mark,
            unmark=unmark,
            delete=delete,
            process=process,
        ),
        patch.object(
            ch.pipeline,
            "fetch_image",
            AsyncMock(side_effect=[None, b"\xff\xd8\xffxx"]),
        ),
    ):
        await ch.handle_channel_post(object(), upd)
    process.assert_awaited_once()
    delete.assert_not_awaited()
    unmark.assert_not_awaited()


async def test_channel_disabled_is_noop():
    off = Channel(id=1, user_id=7, chat_id=99, title="c", enabled=False)
    mark = AsyncMock()
    with (
        patch.object(ch.ch_repo, "get_by_chat", AsyncMock(return_value=off)),
        patch.object(ch.ch_repo, "mark_processed", mark),
    ):
        await ch.handle_channel_post(object(), _UPD)
    mark.assert_not_awaited()
