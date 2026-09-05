from unittest.mock import AsyncMock, patch

from app.handlers.bot_started import handle_bot_started
from app.handlers import message_created as mc
from app.handlers.message_callback import handle_message_callback
from app.models import Tail, Template, User
from app.renderers.views import Screen
from app.wait import WAIT_WM_IMAGE, clear_wait, get_wait, set_wait

_USER = User(id=1, max_user_id=7, name="n")


def _upd(*, text="", atts=None, chat_type="dialog"):
    return {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 7, "first_name": "n"},
            "recipient": {"chat_type": chat_type, "chat_id": 1},
            "body": {"text": text, "mid": "m1", "attachments": atts or []},
        },
    }


async def test_bot_started_opens_templates_and_clears_wait():
    set_wait(9, WAIT_WM_IMAGE)
    with (
        patch(
            "app.handlers.bot_started.user_repo.upsert_user",
            AsyncMock(return_value=User(id=1, max_user_id=9, name="")),
        ),
        patch("app.handlers.bot_started.views.show_templates", AsyncMock()) as show,
    ):
        await handle_bot_started(object(), {"user": {"user_id": 9}})
    show.assert_awaited()
    assert get_wait(9) is None


async def test_unknown_callback_answers():
    ans = AsyncMock()
    with (
        patch(
            "app.handlers.message_callback.user_repo.upsert_user",
            AsyncMock(return_value=_USER),
        ),
        patch("app.handlers.message_callback.answer_callback", ans),
    ):
        await handle_message_callback(
            object(),
            {
                "callback": {
                    "callback_id": "c1",
                    "payload": "nope:x",
                    "user": {"user_id": 7},
                }
            },
        )
    ans.assert_awaited()
    assert ans.await_args.kwargs.get("notification") == "неизвестная кнопка"


async def test_known_callback_acks_then_replaces_without_callback_id():
    ans = AsyncMock()
    seen = []

    async def capture(self, text, kb, photo=None):
        seen.append(self)

    with (
        patch(
            "app.handlers.message_callback.user_repo.upsert_user",
            AsyncMock(return_value=_USER),
        ),
        patch("app.handlers.message_callback.answer_callback", ans),
        patch("app.renderers.views.tpl_repo.list_for", AsyncMock(return_value=[])),
        patch.object(Screen, "show", capture),
    ):
        await handle_message_callback(
            object(),
            {
                "callback": {
                    "callback_id": "c1",
                    "payload": "tab:tpl",
                    "user": {"user_id": 7},
                    "message": {"body": {"mid": "m9"}},
                }
            },
        )
    ans.assert_awaited_once_with("c1", "")
    assert seen
    assert seen[0].replace_mid == "m9"
    assert not hasattr(seen[0], "callback_id")


async def test_start_clears_wait_before_ingest():
    set_wait(7, WAIT_WM_IMAGE)
    with (
        patch.object(mc.user_repo, "upsert_user", AsyncMock(return_value=_USER)),
        patch.object(mc.views, "show_templates", AsyncMock()) as show,
        patch.object(mc, "_ingest_template", AsyncMock()) as ingest,
    ):
        await mc.handle_message_created(object(), _upd(text="/start"))
    show.assert_awaited()
    ingest.assert_not_awaited()


async def test_channel_type_goes_to_channel_handler():
    with patch.object(mc, "handle_channel_post", AsyncMock()) as h:
        await mc.handle_message_created(
            object(),
            _upd(chat_type="channel", atts=[{"type": "image", "payload": {"token": "t"}}]),
        )
    h.assert_awaited()


async def test_unsupported_sticker_message():
    send = AsyncMock()
    with (
        patch.object(mc.user_repo, "upsert_user", AsyncMock(return_value=_USER)),
        patch.object(mc.max_api, "send_to_user", send),
    ):
        await mc.handle_message_created(
            object(),
            _upd(atts=[{"type": "sticker", "payload": {"code": "x"}}]),
        )
    send.assert_awaited()
    assert send.await_args.args[1] == "этот тип не поддерживается"


async def test_round_video_unsupported():
    send = AsyncMock()
    with (
        patch.object(mc.user_repo, "upsert_user", AsyncMock(return_value=_USER)),
        patch.object(mc.max_api, "send_to_user", send),
        patch.object(mc, "_apply_items", AsyncMock()) as apply,
    ):
        await mc.handle_message_created(
            object(),
            _upd(atts=[{"type": "video", "payload": {"token": "t", "is_round": True}}]),
        )
    send.assert_awaited()
    assert send.await_args.args[1] == "этот тип не поддерживается"
    apply.assert_not_awaited()


async def test_file_without_suffix_goes_to_photo():
    apply = AsyncMock()
    with (
        patch.object(mc.user_repo, "upsert_user", AsyncMock(return_value=_USER)),
        patch.object(mc, "_apply_items", apply),
    ):
        await mc.handle_message_created(
            object(),
            _upd(atts=[{"type": "file", "payload": {"token": "raw"}}]),
        )
    apply.assert_awaited()
    assert apply.await_args.args[2][0][0] == "photo"


async def test_png_file_goes_to_photo():
    apply = AsyncMock()
    with (
        patch.object(mc.user_repo, "upsert_user", AsyncMock(return_value=_USER)),
        patch.object(mc, "_apply_items", apply),
    ):
        await mc.handle_message_created(
            object(),
            _upd(
                atts=[
                    {
                        "type": "file",
                        "payload": {"token": "f1", "filename": "mark.png"},
                    }
                ]
            ),
        )
    apply.assert_awaited()
    assert apply.await_args.args[2][0][0] == "photo"


async def test_dm_photo_without_template():
    send = AsyncMock()
    with (
        patch.object(mc.user_repo, "upsert_user", AsyncMock(return_value=_USER)),
        patch.object(mc.pipeline, "resolve_template", AsyncMock(return_value=None)),
        patch.object(mc.max_api, "send_to_user", send),
    ):
        await mc.handle_message_created(
            object(),
            _upd(atts=[{"type": "image", "payload": {"token": "t"}}]),
        )
    assert send.await_args.args[1] == "Сначала добавьте водяной знак."


async def test_mp4_file_goes_to_video():
    apply = AsyncMock()
    with (
        patch.object(mc.user_repo, "upsert_user", AsyncMock(return_value=_USER)),
        patch.object(mc, "_apply_items", apply),
    ):
        await mc.handle_message_created(
            object(),
            _upd(
                atts=[
                    {
                        "type": "file",
                        "payload": {"token": "v1", "filename": "clip.mp4"},
                    }
                ]
            ),
        )
    apply.assert_awaited()
    assert apply.await_args.args[2][0][0] == "video"


async def test_dm_album_applies_each_photo():
    apply = AsyncMock()
    with (
        patch.object(mc.user_repo, "upsert_user", AsyncMock(return_value=_USER)),
        patch.object(mc, "_apply_items", apply),
    ):
        await mc.handle_message_created(
            object(),
            _upd(
                atts=[
                    {"type": "image", "payload": {"token": "a"}},
                    {"type": "image", "payload": {"token": "b"}},
                ]
            ),
        )
    apply.assert_awaited_once()
    items = apply.await_args.args[2]
    assert [k for k, _ in items] == ["photo", "photo"]
    assert [p["token"] for _, p in items] == ["a", "b"]


async def test_dm_album_one_progress_then_each_item():
    send = AsyncMock()
    process = AsyncMock(return_value={"ok": True})
    fetch = AsyncMock(return_value=b"\xff\xd8\xffxx")
    tpl = Template(id=1, user_id=1, name="t", file_path="p.png")
    with (
        patch.object(mc.user_repo, "upsert_user", AsyncMock(return_value=_USER)),
        patch.object(mc.pipeline, "resolve_template", AsyncMock(return_value=tpl)),
        patch.object(mc.max_api, "send_to_user", send),
        patch.object(mc.pipeline, "fetch_image", fetch),
        patch.object(mc.pipeline, "process_media", process),
    ):
        await mc.handle_message_created(
            object(),
            _upd(
                atts=[
                    {"type": "image", "payload": {"token": "a"}},
                    {"type": "image", "payload": {"token": "b"}},
                ]
            ),
        )
    assert send.await_count == 1
    assert send.await_args.args[1] == "Обрабатываю…"
    assert fetch.await_count == 2
    assert process.await_count == 2
    assert [c.kwargs["kind"] for c in process.await_args_list] == ["photo", "photo"]


async def test_dm_album_continues_on_download_miss():
    send = AsyncMock()
    process = AsyncMock(return_value={"ok": True})
    fetch = AsyncMock(side_effect=[None, b"\xff\xd8\xffxx"])
    tpl = Template(id=1, user_id=1, name="t", file_path="p.png")
    with (
        patch.object(mc.user_repo, "upsert_user", AsyncMock(return_value=_USER)),
        patch.object(mc.pipeline, "resolve_template", AsyncMock(return_value=tpl)),
        patch.object(mc.max_api, "send_to_user", send),
        patch.object(mc.pipeline, "fetch_image", fetch),
        patch.object(mc.pipeline, "process_media", process),
    ):
        await mc.handle_message_created(
            object(),
            _upd(
                atts=[
                    {"type": "image", "payload": {"token": "a"}},
                    {"type": "image", "payload": {"token": "b"}},
                ]
            ),
        )
    assert [c.args[1] for c in send.await_args_list] == [
        "Обрабатываю…",
        "Не скачал фото.",
    ]
    process.assert_awaited_once()


async def test_wait_template_skips_video_file():
    set_wait(7, WAIT_WM_IMAGE)
    send = AsyncMock()
    download = AsyncMock()
    with (
        patch.object(mc.user_repo, "upsert_user", AsyncMock(return_value=_USER)),
        patch.object(mc.max_api, "send_to_user", send),
        patch.object(mc.max_api, "download_payload", download),
    ):
        await mc.handle_message_created(
            object(),
            _upd(
                atts=[
                    {
                        "type": "file",
                        "payload": {"token": "v1", "filename": "clip.mp4"},
                    }
                ]
            ),
        )
    assert send.await_args.args[1] == "Нужна картинка. Пришлите файл или фото."
    download.assert_not_awaited()
    assert get_wait(7) == WAIT_WM_IMAGE
    clear_wait(7)


async def test_dm_video_progress_and_resolve_tail():
    send = AsyncMock()
    process = AsyncMock(return_value={"ok": True})
    download = AsyncMock(return_value=b"mp4bytes")
    fetch = AsyncMock()
    delete = AsyncMock()
    tail = Tail(id=2, user_id=1, name="h", file_path="h.mp4")
    tpl = Template(id=1, user_id=1, name="t", file_path="p.png")
    with (
        patch.object(mc.user_repo, "upsert_user", AsyncMock(return_value=_USER)),
        patch.object(mc.pipeline, "resolve_template", AsyncMock(return_value=tpl)),
        patch.object(mc.pipeline, "resolve_tail", AsyncMock(return_value=tail)),
        patch.object(mc.max_api, "send_to_user", send),
        patch.object(mc.max_api, "download_payload", download),
        patch.object(mc.max_api, "delete_message", delete),
        patch.object(mc.pipeline, "fetch_image", fetch),
        patch.object(mc.pipeline, "process_media", process),
    ):
        await mc.handle_message_created(
            object(),
            _upd(atts=[{"type": "video", "payload": {"token": "vid"}}]),
        )
    assert send.await_args.args[1] == "Обрабатываю видео…"
    fetch.assert_not_awaited()
    download.assert_awaited_once()
    delete.assert_not_awaited()
    assert process.await_args.kwargs["kind"] == "video"
    assert process.await_args.kwargs["tail"] is tail
    assert process.await_args.kwargs.get("chat_id") is None


async def test_dm_mixed_tail_only_on_video():
    send = AsyncMock()
    process = AsyncMock(return_value={"ok": True})
    download = AsyncMock(return_value=b"mp4bytes")
    fetch = AsyncMock(return_value=b"\xff\xd8\xffxx")
    delete = AsyncMock()
    resolve_tail = AsyncMock(return_value=None)
    tpl = Template(id=1, user_id=1, name="t", file_path="p.png")
    with (
        patch.object(mc.user_repo, "upsert_user", AsyncMock(return_value=_USER)),
        patch.object(mc.pipeline, "resolve_template", AsyncMock(return_value=tpl)),
        patch.object(mc.pipeline, "resolve_tail", resolve_tail),
        patch.object(mc.max_api, "send_to_user", send),
        patch.object(mc.max_api, "download_payload", download),
        patch.object(mc.max_api, "delete_message", delete),
        patch.object(mc.pipeline, "fetch_image", fetch),
        patch.object(mc.pipeline, "process_media", process),
    ):
        await mc.handle_message_created(
            object(),
            _upd(
                atts=[
                    {"type": "image", "payload": {"token": "pic"}},
                    {"type": "video", "payload": {"token": "vid"}},
                ]
            ),
        )
    assert send.await_args.args[1] == "Обрабатываю…"
    fetch.assert_awaited_once()
    download.assert_awaited_once()
    resolve_tail.assert_awaited_once()
    delete.assert_not_awaited()
    assert [c.kwargs["kind"] for c in process.await_args_list] == ["photo", "video"]
    assert process.await_args_list[0].kwargs["tail"] is None
    assert process.await_args_list[1].kwargs["tail"] is None


async def test_dm_video_continues_on_download_miss():
    send = AsyncMock()
    process = AsyncMock(return_value={"ok": True})
    download = AsyncMock(side_effect=[None, b"mp4bytes"])
    tpl = Template(id=1, user_id=1, name="t", file_path="p.png")
    with (
        patch.object(mc.user_repo, "upsert_user", AsyncMock(return_value=_USER)),
        patch.object(mc.pipeline, "resolve_template", AsyncMock(return_value=tpl)),
        patch.object(mc.pipeline, "resolve_tail", AsyncMock(return_value=None)),
        patch.object(mc.max_api, "send_to_user", send),
        patch.object(mc.max_api, "download_payload", download),
        patch.object(mc.pipeline, "process_media", process),
    ):
        await mc.handle_message_created(
            object(),
            _upd(
                atts=[
                    {"type": "video", "payload": {"token": "a"}},
                    {"type": "video", "payload": {"token": "b"}},
                ]
            ),
        )
    assert [c.args[1] for c in send.await_args_list] == [
        "Обрабатываю видео…",
        "Не скачал видео.",
    ]
    process.assert_awaited_once()
