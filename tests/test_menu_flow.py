"""Exercise real renderers and MAX serialization, mocking only storage and transport."""
import io
import json
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from app import state
from app.api import max_api
from app.engine import apply
from app.handlers import background, bot_started, message_callback as cb, message_created as mc, rounding
from app.keyboards.builders import tabs_kb
from app.models import Channel, DayStats, Tail, Template, User
from app.renderers import views
from app.wait import clear_wait, get_wait


@pytest.fixture
def flow(tmp_path, monkeypatch):
    user = User(id=915, max_user_id=915, name="flow")
    monkeypatch.setattr(apply, "DATA_DIR", tmp_path)
    mark = tmp_path / "mark.png"
    Image.new("RGBA", (20, 20), "blue").save(mark)
    tpl = Template(id=9, user_id=user.id, name="mark", file_path=str(mark), is_default=True)
    channel = Channel(id=4, user_id=user.id, chat_id=123, title="channel")
    tail = Tail(id=2, user_id=user.id, name="tail", file_path=str(tmp_path / "tail.mp4"))
    image = io.BytesIO()
    Image.new("RGB", (80, 40), "white").save(image, "PNG")
    store, events = {}, []
    counter = 0

    async def post(*, json_body, **kwargs):
        nonlocal counter
        counter += 1
        mid = f"m{counter}"
        store[mid] = json_body
        events.append(("send", mid, json_body))
        return 200, json.dumps({"message": {"body": {"mid": mid}}})

    async def delete(*args, params, **kwargs):
        events.append(("delete", params["message_id"]))
        store.pop(params["message_id"], None)
        return 200, '{"success":true}'

    monkeypatch.setattr(max_api, "_post_messages", post)
    monkeypatch.setattr(max_api, "_delete", delete)
    put = AsyncMock(side_effect=AssertionError("Menu transitions must not PUT a photo"))
    monkeypatch.setattr(max_api, "_put", put)
    monkeypatch.setattr(max_api, "upload_memory_get_payload", AsyncMock(return_value={"token": "ready"}))
    monkeypatch.setattr(max_api, "download_payload", AsyncMock(return_value=image.getvalue()))
    monkeypatch.setattr(cb, "answer_callback", AsyncMock())
    monkeypatch.setattr(cb.user_repo, "upsert_user", AsyncMock(return_value=user))
    monkeypatch.setattr(cb.tpl_repo, "list_for", AsyncMock(return_value=[tpl]))
    monkeypatch.setattr(cb.tpl_repo, "get_default", AsyncMock(return_value=tpl))
    monkeypatch.setattr(cb.tpl_repo, "get", AsyncMock(return_value=tpl))
    monkeypatch.setattr(cb.tails_repo, "list_for", AsyncMock(return_value=[]))
    monkeypatch.setattr(cb.tails_repo, "tails_enabled", AsyncMock(return_value=False))
    monkeypatch.setattr(cb.tails_repo, "create", AsyncMock(return_value=tail))
    monkeypatch.setattr(cb.ch_repo, "list_for", AsyncMock(return_value=[channel]))
    monkeypatch.setattr(cb.ch_repo, "get", AsyncMock(return_value=channel))
    monkeypatch.setattr(cb.ch_repo, "upsert", AsyncMock(return_value=channel))
    monkeypatch.setattr(views, "get_chat", AsyncMock(return_value={"link": "https://max.ru/test", "title": "channel"}))
    monkeypatch.setattr(max_api, "get_chat", AsyncMock(return_value={"title": "channel"}))
    monkeypatch.setattr(views.jobs_repo, "today_stats", AsyncMock(return_value=DayStats(0, 0, 0)))
    monkeypatch.setattr(mc.pipeline.jobs_repo, "record", AsyncMock())
    monkeypatch.setattr(mc, "duration_seconds", lambda path: 1)

    async def message(text="", attachments=None, link=None):
        await mc.handle_message_created(None, {"message": {
            "sender": {"user_id": user.max_user_id}, "recipient": {"chat_type": "dialog"},
            "body": {"text": text, "attachments": attachments or []}, "link": link,
        }})

    def buttons():
        current = store[state.UI_MID[user.max_user_id]]
        return next(a["payload"]["buttons"] for a in current["attachments"] if a["type"] == "inline_keyboard")

    async def click(text):
        button = next(b for row in buttons() for b in row if b["text"] == text)
        await cb.handle_message_callback(None, {"callback": {
            "user": {"user_id": user.max_user_id}, "callback_id": "cb", "payload": button["payload"],
            "message": {"body": {"mid": state.UI_MID[user.max_user_id]}},
        }})

    yield user, store, events, message, click, buttons
    clear_wait(user.max_user_id)
    state.TEMPLATE_RETURN.pop(user.max_user_id, None)
    rounding._inputs.pop(user.max_user_id, None)
    background._inputs.pop(user.max_user_id, None)
    put.assert_not_awaited()


async def test_real_menu_transitions_and_back(flow):
    user, store, events, message, click, buttons = flow
    await message("/start")
    await message("/start")
    assert len(store) == 1
    assert buttons() == tabs_kb("")
    for section in ("🖼 Шаблоны", "〽️ Хвосты", "🌝 Округление", "◻️ Убрать фон", "🤖 Авто замена в канале", "👤 Профиль"):
        await click(section)
        if section == "🖼 Шаблоны":
            await click("⚙️ Редактировать")
            await click("Ширина")
            assert store[state.UI_MID[user.max_user_id]]["text"] == "Ширина знака (% кадра)"
            await click("← Назад")
            await click("← Назад")
        elif section == "🌝 Округление":
            await click("Стандартный")
            assert get_wait(user.max_user_id) == rounding.WAIT_ROUND_IMAGE
            await click("← Назад")
        elif section == "◻️ Убрать фон":
            await click("➕ Загрузить")
            await click("← Назад")
            assert store[state.UI_MID[user.max_user_id]]["text"] == background.BODY
        elif section == "🤖 Авто замена в канале":
            await click("✅ channel")
            await click("← Назад")
        await click("← Назад")
        assert buttons() == tabs_kb("")
        assert get_wait(user.max_user_id) is None
        assert len(store) == 1
    for i, event in enumerate(events):
        if event[0] == "delete":
            assert events[i - 1][0] == "send"  # Delivery precedes removal of the old screen.


async def test_photo_status_result_menu_order_and_failure_safety(flow, monkeypatch):
    user, store, events, message, click, buttons = flow
    await message("/start")
    events.clear()
    await message(attachments=[{"type": "image", "payload": {"token": "source"}}])
    sent = [e[2] for e in events if e[0] == "send"]
    assert [m["text"] for m in sent] == ["🔄 **Обрабатываем изображение..**", "Готово", "Главное меню"]
    assert sent[0]["format"] == "markdown" and "attachments" not in sent[0]
    assert len(store) == 2  # The result remains, while the progress and old menu are gone.
    assert buttons() == tabs_kb("")
    old_mid = state.UI_MID[user.max_user_id]
    monkeypatch.setattr(max_api, "_post_messages", AsyncMock(return_value=(200, '{"success":false}')))
    await click("🖼 Шаблоны")
    assert old_mid in store and state.UI_MID[user.max_user_id] == old_mid


@pytest.mark.parametrize("kind", ["tail", "channel"])
async def test_successful_input_replaces_its_prompt(flow, kind):
    user, store, events, message, click, buttons = flow
    await message("/start")
    if kind == "tail":
        await click("〽️ Хвосты")
        await click("+ Новый видеохвостик")
        await message(attachments=[{"type": "video", "payload": {"token": "video"}}])
    else:
        await click("🤖 Авто замена в канале")
        await click("+ Канал")
        await message(link={"type": "forward", "chat_id": 123})
    assert get_wait(user.max_user_id) is None
    assert len(store) == 1
    await click("← Назад")
    await click("← Назад")
    assert buttons() == tabs_kb("")


@pytest.mark.parametrize("section,upload,body", [
    ("🌝 Округление", "Стандартный", rounding.BODY),
    ("◻️ Убрать фон", "➕ Загрузить", background.BODY),
])
async def test_album_keeps_both_downloads_then_returns_to_normal_photo_mode(flow, section, upload, body):
    user, store, events, message, click, buttons = flow
    await message("/start")
    await click(section)
    await click(upload)
    await message(attachments=[{"type": "image", "payload": {"token": token}} for token in ["a", "b"]])
    results = [(mid, data) for mid, data in store.items() if data.get("text") == body]
    assert len(results) == 2
    assert get_wait(user.max_user_id) is None
    for mid, data in results:
        download = next(b for a in data["attachments"] if a["type"] == "inline_keyboard"
                        for row in a["payload"]["buttons"] for b in row if b["text"] == "📥 Скачать изображение")
        await cb.handle_message_callback(None, {"callback": {
            "user": {"user_id": user.max_user_id}, "callback_id": "cb", "payload": download["payload"],
            "message": {"body": {"mid": mid}},
        }})
    assert sum(a["type"] == "file" for data in store.values() for a in data.get("attachments", [])) == 2
    await message(attachments=[{"type": "image", "payload": {"token": "ordinary"}}])
    assert buttons() == tabs_kb("")
    assert any(data.get("text") == "Готово" for data in store.values())
    assert not any(data.get("text") == views.PROCESSING_IMAGE for data in store.values())


@pytest.mark.parametrize("start", ["command", "bot_started"])
async def test_start_hides_downloads_until_new_successful_processing(flow, monkeypatch, start):
    user, store, events, message, click, buttons = flow
    sections = [("🌝 Округление", "Стандартный", rounding),
                ("◻️ Убрать фон", "➕ Загрузить", background)]

    def download_button():
        return next((b for row in buttons() for b in row
                     if b["text"] == "📥 Скачать изображение"), None)

    await message("/start")
    originals = []
    for section, upload, handler in sections:
        await click(section)
        assert download_button() is None
        await click(upload)
        await message(attachments=[{"type": "image", "payload": {"token": "image"}}])
        assert download_button() is not None
        originals.append(handler._latest(user))
        await click("← Назад")

    if start == "command":
        await message("/start")
    else:
        await bot_started.handle_bot_started(None, {"user": {"user_id": user.max_user_id}})

    for section, upload, handler in sections:
        await click(section)
        assert download_button() is None
        await click(upload)
        with monkeypatch.context() as failed:
            failed.setattr(max_api, "download_payload", AsyncMock(return_value=b"invalid image"))
            await message(attachments=[{"type": "image", "payload": {"token": "bad"}}])
        await click("← Назад")
        assert download_button() is None
        await click(upload)
        await message(attachments=[{"type": "image", "payload": {"token": "new"}}])
        assert download_button()["payload"].endswith(handler._latest(user).stem)
        await click("📥 Скачать изображение")
        assert any(a["type"] == "file" for data in store.values() for a in data.get("attachments", []))
        await click("← Назад")

    assert all(path.is_file() for path in originals)
