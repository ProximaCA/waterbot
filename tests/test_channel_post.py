import asyncio
import io
import json
from asyncio import Semaphore
from asyncio import sleep as real_sleep
from copy import deepcopy
from threading import Event
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from app.engine import apply
from app.handlers import channel as ch
from app.models import Channel, Tail, Template, User

USER = User(id=7, max_user_id=100, name="test")
TPL = Template(id=3, user_id=7, name="t", file_path="p.png")
CHANNEL = Channel(id=1, user_id=7, chat_id=99, title="c", template_id=3, use_tail=True)
TAIL = Tail(id=9, user_id=7, name="tail", file_path="tail.mp4")


def update(*, attachments=None, text="Подпись *буквально*", markup=None):
    return {"message": {"recipient": {"chat_id": 99, "chat_type": "channel"}, "body": {
        "mid": "original", "text": text, "markup": markup or [],
        "attachments": attachments if attachments is not None else [
            {"type": "image", "payload": {"token": "a"}},
            {"type": "video", "payload": {"token": "b"}},
            {"type": "file", "payload": {"token": "c", "filename": "photo.png"}},
        ],
    }}}


@pytest.fixture
def api(monkeypatch):
    async def upload(user, template, tail, kind, data):
        return {"type": "image" if kind == "photo" else "video", "payload": {"token": "new-" + data.decode()}}, 12

    mocks = {
        "source": update()["message"],
        "mark": AsyncMock(return_value=True), "unmark": AsyncMock(),
        "upload": AsyncMock(side_effect=upload), "delete": AsyncMock(),
        "post": AsyncMock(), "put": AsyncMock(return_value=(200, '{"success":true}')),
        "fetch": AsyncMock(side_effect=lambda payload: payload["token"].encode()),
        "tail": AsyncMock(return_value=TAIL), "template": AsyncMock(return_value=TPL),
        "record": AsyncMock(), "channel": AsyncMock(return_value=CHANNEL),
        "sleep": AsyncMock(),
    }
    mocks["get"] = AsyncMock(side_effect=lambda *a, **kw: (200, json.dumps({"messages": [mocks["source"]]})))
    monkeypatch.setattr(ch.ch_repo, "get_by_chat", mocks["channel"])
    monkeypatch.setattr(ch.ch_repo, "mark_processed", mocks["mark"])
    monkeypatch.setattr(ch.ch_repo, "unmark_processed", mocks["unmark"])
    monkeypatch.setattr(ch.user_repo, "get_by_id", AsyncMock(return_value=USER))
    monkeypatch.setattr(ch.pipeline, "resolve_template", mocks["template"])
    monkeypatch.setattr(ch.pipeline, "fetch_image", mocks["fetch"])
    monkeypatch.setattr(ch.pipeline, "_record", mocks["record"])
    monkeypatch.setattr(ch.tails_repo, "get_default", mocks["tail"])
    monkeypatch.setattr(ch.max_api, "download_payload", mocks["fetch"])
    monkeypatch.setattr(ch.max_api, "_get", mocks["get"])
    monkeypatch.setattr(ch.max_api, "_put", mocks["put"])
    monkeypatch.setattr(ch.max_api, "_post_messages", mocks["post"])
    monkeypatch.setattr(ch.max_api, "delete_message", mocks["delete"])
    monkeypatch.setattr(ch, "_upload_item", mocks["upload"])
    monkeypatch.setattr(ch.asyncio, "sleep", mocks["sleep"])
    monkeypatch.setattr(ch, "_media_sem", Semaphore(4))
    ch._locks.clear()
    yield mocks
    # In-place processing must NEVER create a post or delete the original, even on errors.
    mocks["post"].assert_not_awaited()
    mocks["delete"].assert_not_awaited()


async def test_album_edits_original_mid_and_preserves_caption_and_order(api):
    api["source"]["body"]["markup"] = [{"type": "future", "from": 0, "length": 2}]
    before = deepcopy(api["source"])
    await ch.handle_channel_post(None, update())
    sent = api["put"].await_args.kwargs
    assert sent["params"] == {"message_id": "original"}
    assert set(sent["json_body"]) == {"attachments"}  # Text, formatting and reply/forward stay on MAX.
    assert [a["payload"]["token"] for a in sent["json_body"]["attachments"]] == ["new-a", "new-b", "new-c"]
    assert [a["type"] for a in sent["json_body"]["attachments"]] == ["image", "video", "image"]
    assert [call.args[2] for call in api["upload"].await_args_list] == [None, TAIL, None]
    api["mark"].assert_awaited_once_with(None, 99, "original")
    api["unmark"].assert_not_awaited()
    assert api["record"].await_count == 3
    assert api["source"] == before


async def test_ten_attachments_overlap_but_keep_original_order(api):
    api["source"]["body"]["attachments"] = [
        {"type": "image" if i % 2 == 0 else "video", "payload": {"token": str(i)}}
        for i in range(10)
    ]
    active = peak = 0

    async def upload(user, template, tail, kind, data):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await real_sleep(0.02 if int(data) % 2 else 0.04)
        active -= 1
        return {"type": "image" if kind == "photo" else "video",
                "payload": {"token": "new-" + data.decode()}}, 12

    api["upload"].side_effect = upload
    await ch.handle_channel_post(None, update())
    assert peak == 4
    assert [a["payload"]["token"] for a in api["put"].await_args.kwargs["json_body"]["attachments"]] == [
        f"new-{i}" for i in range(10)
    ]
    assert [a["type"] for a in api["put"].await_args.kwargs["json_body"]["attachments"]] == [
        "image" if i % 2 == 0 else "video" for i in range(10)
    ]
    assert {call.args[4].decode(): call.args[2] for call in api["upload"].await_args_list} == {
        str(i): None if i % 2 == 0 else TAIL for i in range(10)
    }
    assert api["record"].await_count == 10


async def test_failed_parallel_item_drains_siblings_before_releasing_claim(api):
    api["source"]["body"]["attachments"] = [
        {"type": "image", "payload": {"token": str(i)}} for i in range(10)
    ]
    finished = []

    async def upload(user, template, tail, kind, data):
        await real_sleep(0.01 if data == b"3" else 0.03)
        finished.append(data)
        if data == b"3":
            raise RuntimeError("bad upload")
        return {"type": "image", "payload": {"token": data.decode()}}, 12

    async def unmark(*args):
        assert len(finished) == 10

    api["upload"].side_effect = upload
    api["unmark"].side_effect = unmark
    await ch.handle_channel_post(None, update())
    api["put"].assert_not_awaited()
    api["unmark"].assert_awaited_once_with(None, 99, "original")


async def test_two_posts_in_same_channel_process_concurrently(api):
    active = peak = 0

    async def get(*args, params, **kwargs):
        message = update()["message"]
        message["body"]["mid"] = params["message_ids"]
        message["body"]["attachments"] = [
            {"type": "image", "payload": {"token": params["message_ids"]}}
        ]
        return 200, json.dumps({"messages": [message]})

    async def upload(user, template, tail, kind, data):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await real_sleep(0.03)
        active -= 1
        return {"type": "image", "payload": {"token": data.decode()}}, 12

    api["get"].side_effect = get
    api["upload"].side_effect = upload
    first, second = update(), update()
    first["message"]["body"]["mid"] = "first"
    second["message"]["body"]["mid"] = "second"
    await asyncio.gather(
        ch.handle_channel_post(None, first), ch.handle_channel_post(None, second))
    assert peak == 2
    assert sorted(call.kwargs["params"]["message_id"] for call in api["put"].await_args_list) == [
        "first", "second"]


async def test_duplicate_post_waits_for_failed_attempt_then_retries(api):
    api["source"]["body"]["attachments"] = [
        {"type": "image", "payload": {"token": "photo"}}
    ]
    claimed = False
    attempts = 0

    async def mark(*args):
        nonlocal claimed
        if claimed:
            return False
        claimed = True
        return True

    async def unmark(*args):
        nonlocal claimed
        claimed = False

    async def upload(user, template, tail, kind, data):
        nonlocal attempts
        attempts += 1
        await real_sleep(0.02)
        if attempts == 1:
            raise RuntimeError("temporary upload error")
        return {"type": "image", "payload": {"token": "new-photo"}}, 12

    api["mark"].side_effect = mark
    api["unmark"].side_effect = unmark
    api["upload"].side_effect = upload
    await asyncio.gather(ch.handle_channel_post(None, update()),
                         ch.handle_channel_post(None, update()))
    assert attempts == 2
    api["unmark"].assert_awaited_once_with(None, 99, "original")
    api["put"].assert_awaited_once()


async def test_fresh_comment_keyboard_is_preserved_after_rendering(api):
    first = deepcopy(api["source"])
    button = {"type": "link", "text": "💭 Прокомментировать", "url": "https://max.ru/comments_bot?startapp=cmt_337"}
    keyboard = {"type": "inline_keyboard", "payload": {"buttons": [[button]]}}
    api["source"]["body"]["attachments"].append(keyboard)
    api["get"].side_effect = [(200, json.dumps({"messages": [m]})) for m in [first, api["source"]]]
    await ch.handle_channel_post(None, update(attachments=[]))  # Webhook snapshot can omit media.
    assert api["put"].await_args.kwargs["json_body"]["attachments"][-1] == keyboard
    assert api["get"].await_count == 2


@pytest.mark.parametrize("changed_photo", [False, True])
@pytest.mark.parametrize("kind,id_field", [("image", "photo_id"), ("video", "id")])
async def test_rotating_media_token_does_not_mean_the_author_changed_media(api, changed_photo, kind, id_field):
    api["source"]["body"]["attachments"][0] = {"type": kind, "payload": {"token": "a", id_field: 123}}
    first = deepcopy(api["source"])
    api["source"]["body"]["attachments"][0]["payload"].update({
        "token": "refreshed-token", id_field: 456 if changed_photo else 123,
    })
    api["get"].side_effect = [(200, json.dumps({"messages": [m]})) for m in [first, api["source"]]]
    await ch.handle_channel_post(None, update())
    assert api["put"].await_count == (0 if changed_photo else 1)


@pytest.mark.parametrize("failure", ["read", "fetch", "upload", "put", "false_success", "template", "stats"])
async def test_failures_leave_original_post_and_never_republish(api, failure):
    if failure == "read":
        api["get"].side_effect = TimeoutError("network")
    elif failure == "fetch":
        api["fetch"].side_effect = [b"a", None]
    elif failure == "upload":
        api["upload"].side_effect = RuntimeError("failed")
    elif failure == "put":
        api["put"].return_value = (403, '{"code":"forbidden"}')
    elif failure == "false_success":
        api["put"].return_value = (200, '{"success":false}')
    elif failure == "template":
        api["template"].return_value = None
    else:
        api["record"].side_effect = RuntimeError("db")
    await ch.handle_channel_post(None, update())
    if failure in {"read", "fetch", "upload", "template"}:
        api["put"].assert_not_awaited()
    if failure == "stats":
        api["unmark"].assert_not_awaited()  # Already edited; do not watermark twice.
    else:
        api["unmark"].assert_awaited_once_with(None, 99, "original")


async def test_changed_or_deleted_post_is_not_overwritten(api):
    original = deepcopy(api["source"])
    api["source"]["body"]["attachments"][0]["payload"]["token"] = "author-edited"
    api["get"].side_effect = [(200, json.dumps({"messages": [m]})) for m in [original, api["source"]]]
    await ch.handle_channel_post(None, update())
    api["put"].assert_not_awaited()
    api["get"].side_effect = [(200, json.dumps({"messages": [original]})), (200, '{"messages":[]}')]
    await ch.handle_channel_post(None, update())
    api["put"].assert_not_awaited()


async def test_upload_not_ready_retries_edit_on_same_mid_with_fresh_keyboard(api):
    api["put"].side_effect = [(400, '{"code":"attachment.not.ready"}'), (200, '{"success":true}')]
    await ch.handle_channel_post(None, update())
    assert api["put"].await_count == 2
    assert all(c.kwargs["params"] == {"message_id": "original"} for c in api["put"].await_args_list)
    assert api["get"].await_count == 3
    assert api["upload"].await_count == 3


async def test_duplicate_and_disabled_post_are_ignored(api):
    api["mark"].return_value = False
    await ch.handle_channel_post(None, update())
    api["get"].assert_not_awaited()
    api["channel"].return_value = Channel(id=1, user_id=7, chat_id=99, title="c", enabled=False)
    api["mark"].reset_mock()
    await ch.handle_channel_post(None, update())
    api["mark"].assert_not_awaited()


@pytest.mark.parametrize("extra", [
    {"type": "video", "payload": {"token": "v", "is_round": True}},
    {"type": "file", "payload": {"token": "f", "filename": "document.pdf"}},
    {"type": "audio", "payload": {"token": "a"}},
])
async def test_mixed_unsupported_attachments_are_never_discarded(api, extra):
    api["source"]["body"]["attachments"].append(extra)
    await ch.handle_channel_post(None, update())
    api["put"].assert_not_awaited()
    api["upload"].assert_not_awaited()


async def test_active_template_and_disabled_channel_tail(api):
    api["channel"].return_value = Channel(id=1, user_id=7, chat_id=99, title="c")
    await ch.handle_channel_post(None, update())
    api["template"].assert_awaited_once_with(None, USER.id, None)
    api["tail"].assert_not_awaited()
    assert all(call.args[2] is None for call in api["upload"].await_args_list)


async def test_forward_keeps_its_original_caption_link_and_comment(api):
    body = api["source"]["body"]
    api["source"]["body"] = {"mid": "original", "text": "Комментарий"}
    api["source"]["link"] = {"type": "forward", "message": {"body": body}}
    await ch.handle_channel_post(None, update())
    sent = api["put"].await_args.kwargs["json_body"]
    assert set(sent) == {"attachments"}
    assert len(sent["attachments"]) == 3


async def test_upload_uses_real_image_engine_and_cleans_temporary_files(tmp_path, monkeypatch):
    monkeypatch.setattr(apply, "DATA_DIR", tmp_path)
    endpoint = {"url": "https://upload.example/test"}
    get_endpoint = AsyncMock(return_value=endpoint)
    monkeypatch.setattr(ch.max_api, "get_upload_endpoint", get_endpoint)
    source = io.BytesIO()
    Image.new("RGB", (100, 100), "white").save(source, "PNG")
    watermark = tmp_path / "mark.png"
    Image.new("RGBA", (20, 20), "red").save(watermark)
    template = Template(id=3, user_id=7, name="t", file_path=str(watermark))
    async def upload(**kwargs):
        assert kwargs["file_type"] == "image"
        assert kwargs["endpoint"] is endpoint
        result = Image.open(io.BytesIO(kwargs["data"]))
        assert result.getpixel((95, 95))[0] > 200
        assert result.getpixel((95, 95))[1] < 50
        return {"token": "ready"}
    with patch.object(ch.max_api, "upload_memory_get_payload", upload):
        attachment, size = await ch._upload_item(USER, template, None, "photo", source.getvalue())
    assert size > 0 and attachment == {"type": "image", "payload": {"token": "ready"}}
    get_endpoint.assert_awaited_once_with("image")
    assert list((tmp_path / str(USER.id)).iterdir()) == []


async def test_upload_url_is_requested_while_photo_renders(tmp_path, monkeypatch):
    monkeypatch.setattr(apply, "DATA_DIR", tmp_path)
    rendering = Event()
    endpoint_started = Event()

    def render(data, template, dest):
        rendering.set()
        assert endpoint_started.wait(2)
        dest.write_bytes(b"rendered")

    async def get_endpoint(kind):
        assert kind == "image"
        assert await asyncio.to_thread(rendering.wait, 2)
        endpoint_started.set()
        return {"url": "https://upload.example/test"}

    upload = AsyncMock(return_value={"token": "ready"})
    monkeypatch.setattr(ch, "apply_photo", render)
    monkeypatch.setattr(ch.max_api, "get_upload_endpoint", get_endpoint)
    monkeypatch.setattr(ch.max_api, "upload_memory_get_payload", upload)
    await asyncio.wait_for(ch._upload_item(USER, TPL, None, "photo", b"input"), 5)
    assert upload.await_args.kwargs["endpoint"] == {"url": "https://upload.example/test"}
    assert list((tmp_path / str(USER.id)).iterdir()) == []


async def test_prefetched_url_skips_second_request_and_default_path_still_fetches(monkeypatch):
    endpoint = {"url": "https://upload.example/test"}
    get_endpoint = AsyncMock(return_value=endpoint)
    post = AsyncMock(return_value=(200, '{"token":"ready"}'))
    monkeypatch.setattr(ch.max_api, "get_upload_endpoint", get_endpoint)
    monkeypatch.setattr(ch.max_api, "_post", post)

    kwargs = {"file_type": "image", "data": b"image", "filename": "image.jpg"}
    assert await ch.max_api.upload_memory_get_payload(**kwargs, endpoint=endpoint) == {"token": "ready"}
    get_endpoint.assert_not_awaited()
    assert await ch.max_api.upload_memory_get_payload(**kwargs) == {"token": "ready"}
    get_endpoint.assert_awaited_once_with("image")
