from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image, ImageDraw

from app import state
from app.handlers import message_callback as callbacks, message_created as messages
from app.keyboards.builders import position_kb
from app.models import DayStats, Tail, Template, User
from app.renderers import views
from app.wait import WAIT_WM_IMAGE, clear_wait, get_wait


USER = User(id=1, max_user_id=71, name="n")


@pytest.fixture(autouse=True)
def reset_state():
    yield
    clear_wait(USER.max_user_id)
    state.TEMPLATE_UPLOAD.pop(USER.max_user_id, None)
    state.TEMPLATE_RETURN.pop(USER.max_user_id, None)


async def click(payload, mid="old"):
    with (
        patch.object(callbacks.user_repo, "upsert_user", AsyncMock(return_value=USER)),
        patch.object(callbacks, "answer_callback", AsyncMock()),
    ):
        await callbacks.handle_message_callback(object(), {
            "callback": {"callback_id": "cb", "payload": payload,
                         "user": {"user_id": USER.max_user_id},
                         "message": {"body": {"mid": mid}}},
        })


def test_template_prompts_match_spec():
    assert views.templates_body(0) == "🖼 **Шаблоны**\n\nДобавьте новый шаблон"
    assert views.templates_body(1) == "**Шаблоны**\n\nВыберите активные шаблон:"


async def test_position_replaces_photo_and_keeps_controls(tmp_path):
    path = tmp_path / "mark.png"
    Image.new("RGBA", (80, 40), "red").save(path)
    tpl = Template(id=9, user_id=USER.id, name="mark", file_path=str(path))
    events, photos = [], []

    async def delete(mid):
        events.append(("delete", mid))
        return True

    async def send(path, **kwargs):
        events.append(("send", kwargs["keyboard"]))
        photos.append(Image.open(path).copy())
        return {"message": {"body": {"mid": f"new-{len(photos)}"}}}

    with (
        patch.object(callbacks.tpl_repo, "get", AsyncMock(return_value=tpl)),
        patch.object(callbacks.tpl_repo, "update", AsyncMock(
            return_value=replace(tpl, position="nw"))) as update,
        patch.object(views, "delete_message", delete),
        patch.object(views, "send_file", send),
        patch.object(views, "tmp_path", return_value=tmp_path / "preview.jpg"),
    ):
        await click("wm:pos:9")
        await click("wm:setpos:9:nw", mid="new-1")
    assert events == [("send", position_kb(9, "se")), ("delete", "old"),
                      ("send", position_kb(9, "nw")), ("delete", "new-1")]
    assert update.await_count == 1
    assert update.await_args.args[1:] == (9, USER.id)
    assert update.await_args.kwargs == {"position": "nw"}
    assert photos[0].getpixel((10, 10))[0] < 50
    assert photos[1].getpixel((10, 10))[0] > 200
    assert not (tmp_path / "preview.jpg").exists()


async def test_position_still_shows_new_photo_if_old_message_was_already_deleted(tmp_path):
    path = tmp_path / "mark.png"
    Image.new("RGB", (20, 20), "red").save(path)
    tpl = Template(id=9, user_id=USER.id, name="mark", file_path=str(path))
    with (
        patch.object(views, "delete_message", AsyncMock(return_value=False)),
        patch.object(views, "send_file", AsyncMock(return_value={"message": {"body": {"mid": "new"}}})) as send,
        patch.object(views, "tmp_path", return_value=tmp_path / "preview.jpg"),
    ):
        mid = await views.show_position_picker(object(), USER, tpl, views.Screen(71, "old"))
    assert mid == "new"
    send.assert_awaited_once()
    assert not (tmp_path / "preview.jpg").exists()


async def test_select_updates_list_and_border(tmp_path):
    tpl = Template(id=9, user_id=USER.id, name="mark", file_path="missing.png",
                   slot=3, is_default=True)
    captured = []

    async def show(self, text, kb, photo=None):
        captured.append((kb, Image.open(photo).copy()))

    with (
        patch.object(callbacks.tpl_repo, "set_default", AsyncMock()) as select,
        patch.object(views.tpl_repo, "list_for", AsyncMock(side_effect=[
            [replace(tpl, is_default=False)], [tpl]
        ])),
        patch.object(views.Screen, "show", show),
        patch.object(views, "tmp_path", return_value=tmp_path / "sheet.jpg"),
    ):
        await views.show_templates(object(), USER, views.Screen.for_user(USER))
        await click("tpl:select:9")
    assert select.await_args.args[1:] == (9, USER.id)
    kb, photo = captured[0]
    assert kb[2][0]["text"] == "☑️ 3"
    r, g, b = photo.getpixel((445, 110))
    assert not (g > r + 50 and g > b + 50)
    kb, photo = captured[1]
    assert kb[2][0]["text"] == "✅ 3"
    r, g, b = photo.getpixel((445, 110))
    assert g > r + 50 and g > b + 50


async def test_upload_into_third_slot_returns_to_list(tmp_path):
    path = tmp_path / "uploaded.png"
    Image.new("RGBA", (20, 20), "red").save(path)
    ui = views.Screen.for_user(USER, "old")
    with (
        patch.object(callbacks.tpl_repo, "list_for", AsyncMock(return_value=[])),
        patch.object(views, "ask_new_template", AsyncMock(return_value="prompt")),
    ):
        await callbacks._new_template(object(), USER, ui, ["3"])
    assert get_wait(USER.max_user_id) == WAIT_WM_IMAGE
    assert state.TEMPLATE_UPLOAD[USER.max_user_id] == (3, "prompt")
    update = {"message": {"body": {"attachments": [
        {"type": "image", "payload": {"token": "mark"}}
    ]}}}
    with (
        patch.object(messages.max_api, "download_payload", AsyncMock(return_value=path.read_bytes())),
        patch.object(messages.tpl_repo, "list_for", AsyncMock(return_value=[])),
        patch.object(messages.tpl_repo, "create", AsyncMock()) as create,
        patch.object(messages, "store_upload", return_value=path),
        patch.object(views, "show_templates", AsyncMock()) as show,
    ):
        await messages._ingest_template(object(), USER, update)
    assert create.await_args.kwargs["slot"] == 3
    assert create.await_args.kwargs["name"] == "Шаблон 3"
    assert show.await_args.args[2].replace_mid == "prompt"
    assert get_wait(USER.max_user_id) is None


@pytest.mark.parametrize("slot", ["0", "4", "invalid", "3"])
async def test_upload_rejects_invalid_or_occupied_slot(slot):
    tpl = Template(id=9, user_id=USER.id, name="mark", file_path="mark.png", slot=3)
    with (
        patch.object(callbacks.tpl_repo, "list_for", AsyncMock(return_value=[tpl])),
        patch.object(views, "ask_new_template", AsyncMock()) as ask,
        patch.object(views, "show_templates", AsyncMock()) as show,
    ):
        await callbacks._new_template(object(), USER, views.Screen(71), [slot])
    ask.assert_not_awaited()
    show.assert_awaited_once()
    assert get_wait(USER.max_user_id) is None


async def test_back_returns_to_profile_after_template_interactions():
    bodies = []

    async def show(self, text, kb, photo=None):
        bodies.append(text)

    with (
        patch.object(views.jobs_repo, "today_stats", AsyncMock(return_value=DayStats(0, 0, 0))),
        patch.object(views.tpl_repo, "list_for", AsyncMock(return_value=[])),
        patch.object(callbacks.tpl_repo, "set_default", AsyncMock()),
        patch.object(views.Screen, "show", show),
    ):
        await click("tab:me")
        await click("tab:tpl")
        await click("tpl:select:9")
        await click("tpl:back")
    assert bodies[0] == bodies[-1] == views.profile_body(USER, DayStats(0, 0, 0))
    assert bodies[1:3] == [views.templates_body(0)] * 2


async def test_back_without_history_opens_menu():
    with patch.object(views.Screen, "show", AsyncMock()) as show:
        await click("tpl:back")
    assert show.await_args.args[0] == "Главное меню"


async def test_menu_resets_back_destination():
    state.TEMPLATE_RETURN[USER.max_user_id] = ("tab:tails", [])
    with patch.object(views.Screen, "show", AsyncMock()) as show:
        await views.show_menu(object(), USER, views.Screen.for_user(USER))
    assert state.TEMPLATE_RETURN[USER.max_user_id] == ("nav:home", [])
    assert [b["text"] for row in show.await_args.args[1] for b in row] == [
        "🖼 Шаблоны", "〽️ Хвосты", "🌝 Округление", "◻️ Убрать фон",
        "🤖 Авто замена в канале", "👤 Профиль"
    ]


@pytest.mark.parametrize("section,new", [
    ("tab:tpl", "tpl:new:1"), ("tab:tails", "tail:new"),
    ("tab:ch", "ch:add"), ("tab:me", None),
])
async def test_menu_section_cancel_and_back(section, new):
    screens = []

    async def show(self, text, kb, photo=None):
        screens.append((text, kb))
        return "screen"

    with (
        patch.object(views.tpl_repo, "list_for", AsyncMock(return_value=[])),
        patch.object(views.tails_repo, "list_for", AsyncMock(return_value=[])),
        patch.object(views.tails_repo, "tails_enabled", AsyncMock(return_value=False)),
        patch.object(views.ch_repo, "list_for", AsyncMock(return_value=[])),
        patch.object(views.jobs_repo, "today_stats", AsyncMock(return_value=DayStats(0, 0, 0))),
        patch.object(views.Screen, "show", show),
    ):
        await click("nav:home")
        menu = screens[-1]
        await click(section)
        root = screens[-1]
        if new:
            await click(new)
            assert get_wait(USER.max_user_id) is not None
            await click(screens[-1][1][-1][0]["payload"])
            assert get_wait(USER.max_user_id) is None
            assert screens[-1] == root
        await click(screens[-1][1][-1][0]["payload"])
        assert screens[-1] == menu
        await click("tab:tpl")
        await click("tpl:back")
        assert screens[-1] == menu


async def _edit_mark(tmp_path, path, payload):
    tpl = Template(id=9, user_id=USER.id, name="mark", file_path=str(path))
    current = [tpl]
    screens = []

    async def show(self, text, kb, photo=None):
        screens.append((text, [b["text"] for row in kb for b in row], photo))
        return f"m{len(screens)}"

    async def update(pool, tid, user_id, **fields):
        current[0] = replace(current[0], **fields)
        return current[0]

    with (
        patch.object(callbacks.tpl_repo, "get", AsyncMock(side_effect=lambda *a, **k: current[0])),
        patch.object(callbacks.tpl_repo, "update", AsyncMock(side_effect=update)) as save,
        patch.object(views.Screen, "show", show),
        patch.object(views, "tmp_path", return_value=tmp_path / "preview.jpg"),
    ):
        await click(payload)
    return current[0], screens, save


async def test_card_round_rewrites_mark_as_circle_png(tmp_path):
    path = tmp_path / "mark.jpg"
    Image.new("RGB", (80, 40), "red").save(path, "JPEG")
    tpl, screens, save = await _edit_mark(tmp_path, path, "tpl:round:9")
    assert screens[0][0] == views.PROCESSING_IMAGE
    assert screens[-1][0] == views.template_card_body(tpl)
    assert "Округлить" in screens[-1][1] and "Убрать фон" in screens[-1][1]
    out = Path(tpl.file_path)
    assert out.suffix == ".png" and not path.exists()
    save.assert_awaited_once()
    assert save.await_args.kwargs == {"file_path": str(out)}
    with Image.open(out) as result:
        assert result.size == (40, 40) and result.mode == "RGBA"
        assert result.getpixel((0, 0))[3] == 0
        r, g, b = result.getpixel((20, 20))[:3]
        assert r > 250 and g < 5 and b < 5


async def test_pad_picker_shows_axes_and_template(tmp_path):
    path = tmp_path / "mark.png"
    Image.new("RGBA", (40, 40), (0, 180, 0, 255)).save(path)
    tpl = Template(id=9, user_id=USER.id, name="mark", file_path=str(path), pad_x=20, pad_y=0)
    photos = []

    async def send(path, **kwargs):
        photos.append((kwargs.get("caption"), kwargs.get("kind"), Image.open(path).copy()))
        return {"message": {"body": {"mid": "pad"}}}

    with (
        patch.object(callbacks.tpl_repo, "get", AsyncMock(return_value=tpl)),
        patch.object(callbacks.tpl_repo, "update", AsyncMock(
            return_value=replace(tpl, pad_y=20))),
        patch.object(views, "delete_message", AsyncMock(return_value=True)),
        patch.object(views, "send_file", send),
        patch.object(views, "tmp_path", return_value=tmp_path / "pad.jpg"),
    ):
        await click("wm:py:9")
        await click("wm:setpy:9:20")
    assert [p[0] for p in photos] == ["Сдвиг по Y (% кадра)", "Сдвиг по Y (% кадра)"]
    photo = photos[0][2]
    cx, cy = photo.size[0] // 2, photo.size[1] // 2
    assert photo.getpixel((cx + 120, cy))[1] > 120
    assert photo.getpixel((cx, cy))[1] < 80
    moved = photos[1][2]
    assert moved.getpixel((cx + 120, cy + 120))[1] > 120
    assert moved.getpixel((cx + 120, cy))[1] < 80
    assert not (tmp_path / "pad.jpg").exists()


async def test_tail_card_sends_video_and_falls_back_to_text(tmp_path):
    clip = tmp_path / "tail.mp4"
    clip.write_bytes(b"mp4")
    tail = Tail(id=2, user_id=USER.id, name="Хвост 1", file_path=str(clip), placement="end")
    sent = []

    async def send_file(path, **kwargs):
        sent.append(("file", path, kwargs.get("kind"), kwargs.get("caption")))
        return {"message": {"body": {"mid": "vid"}}}

    async def send_message(**kwargs):
        sent.append(("text", kwargs.get("text")))
        return {"message": {"body": {"mid": "txt"}}}

    with (
        patch.object(views, "send_file", send_file),
        patch.object(views, "send_message", send_message),
        patch.object(views, "delete_message", AsyncMock(return_value=True)),
    ):
        await views.show_tail_card(None, USER, tail, views.Screen(USER.max_user_id, "old"))
        missing = replace(tail, file_path=str(tmp_path / "gone.mp4"))
        await views.show_tail_card(None, USER, missing, views.Screen(USER.max_user_id, "vid"))
    assert sent[0][0] == "file" and sent[0][1] == str(clip) and sent[0][2] == "video"
    assert sent[0][3] == views.tail_card_body(tail)
    assert sent[1][0] == "text" and sent[1][1] == views.tail_card_body(missing)


async def test_card_remove_bg_keeps_subject_and_png_path(tmp_path):
    path = tmp_path / "mark.png"
    image = Image.new("RGB", (80, 40), "white")
    ImageDraw.Draw(image).rectangle((20, 10, 59, 29), fill="blue")
    image.save(path, "PNG")
    tpl, screens, save = await _edit_mark(tmp_path, path, "tpl:bg:9")
    assert screens[0][0] == views.PROCESSING_IMAGE
    assert screens[-1][0] == views.template_card_body(tpl)
    assert tpl.file_path == str(path)
    save.assert_not_awaited()
    with Image.open(path) as result:
        assert result.mode == "RGBA"
        assert result.getpixel((0, 0))[3] == 0
        assert result.getpixel((40, 20)) == (0, 0, 255, 255)
