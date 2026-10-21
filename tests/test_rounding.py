import io
import os
import time
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image, ImageDraw

from app.engine import apply
from app.engine.rounding import parse_size, round_image
from app.handlers import rounding
from app.handlers import message_callback as callbacks, message_created as messages
from app.models import User
from app.renderers.views import Screen
from app.wait import clear_wait, get_wait

USER = User(id=900, max_user_id=900, name="rounding")


def image_bytes(fmt="PNG"):
    image = Image.new("RGBA", (200, 100), "red")
    ImageDraw.Draw(image).rectangle((50, 0, 149, 99), fill="blue")
    buffer = io.BytesIO()
    (image.convert("RGB") if fmt == "JPEG" else image).save(buffer, fmt)
    return buffer.getvalue()


def update(text="", *, file=False):
    return {"message": {"body": {"text": text, "attachments": [{
        "type": "file" if file else "image",
        "payload": {"token": "photo", "filename": "photo.png"},
    }] if not text else []}}}


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(apply, "DATA_DIR", tmp_path)
    yield
    clear_wait(USER.max_user_id)
    rounding._inputs.pop(USER.max_user_id, None)
    rounding._locks.pop(USER.max_user_id, None)


def test_square_sizes_and_centered_circle_preserve_transparency():
    for text, size in (("600 600", 600), ("300x300", 300), ("1254 × 1254", 1254)):
        assert parse_size(text) == size
        result = round_image(image_bytes(), size)
        assert result.size == (size, size)
        assert result.getpixel((0, 0))[3] == 0
        assert result.getpixel((size - 1, size - 1))[3] == 0
        assert result.getpixel((size // 2, size // 2)) == (0, 0, 255, 255)
        assert result.getpixel((size // 4, size // 2)) == (0, 0, 255, 255)
    transparent = io.BytesIO()
    Image.new("RGBA", (100, 100), (10, 20, 30, 70)).save(transparent, "PNG")
    assert round_image(transparent.getvalue(), 100).getpixel((50, 50))[3] == 70
    for invalid in ("600 300", "300", "0x0", "4097x4097", "-3 -3", "300x300junk"):
        with pytest.raises(ValueError):
            parse_size(invalid)


async def test_standard_custom_preview_and_original_download():
    screens = []

    async def show(self, text, kb, photo=None):
        screens.append((text, kb, Image.open(photo).copy() if photo else None))
        return f"screen-{len(screens)}"

    with (
        patch.object(Screen, "show", show),
        patch.object(rounding.max_api, "download_payload", AsyncMock(side_effect=[
            image_bytes("JPEG"), image_bytes()
        ])),
        patch.object(rounding.max_api, "send_file", AsyncMock()) as send,
        patch.object(rounding.max_api, "send_to_user", AsyncMock()) as error,
    ):
        await rounding.show(None, USER, Screen.for_user(USER))
        assert screens[-1][0] == rounding.BODY
        assert [b["text"] for row in screens[-1][1] for b in row] == [
            "Стандартный", "Свой размер", "← Назад"
        ]
        assert screens[-1][2].getpixel((280, 320)) == (255, 255, 255)
        await rounding.standard(None, USER, Screen.for_user(USER), [])
        assert screens[-1][0] == "ℹ️ Загрузите изображения формата PNG.\n\n" + rounding.PNG_FILE_NOTE
        await rounding.ingest_images(None, USER, update())
        assert screens[-2][0] == rounding.PROCESSING
        assert screens[-1][0] == rounding.BODY
        first = rounding._latest(USER)
        with Image.open(first) as png:
            assert png.format == "PNG" and png.size == (1254, 1254)
            assert png.getpixel((0, 0))[3] == 0
        texts = [b["text"] for row in screens[-1][1] for b in row]
        assert "📥 Скачать изображение" in texts and "Сброс" in texts
        assert screens[-1][1][-2][0]["payload"] == "round:reset"
        assert get_wait(USER.max_user_id) is None

        await rounding.custom(None, USER, Screen.for_user(USER), [])
        assert "> 600 600\n> 300x300" in screens[-1][0]
        await rounding.ingest_size(None, USER, update("600 300"))
        assert get_wait(USER.max_user_id) == rounding.WAIT_ROUND_SIZE
        error.assert_awaited_once()
        await rounding.ingest_size(None, USER, update("300x300"))
        assert screens[-1][0] == "ℹ️ Теперь, загрузите изображения формата PNG.\n\n" + rounding.PNG_FILE_NOTE
        await rounding.ingest_images(None, USER, update(file=True))
        second = rounding._latest(USER)
        with Image.open(second) as png:
            assert png.size == (300, 300)
        assert first != second

        # A previous menu still downloads its own original, including after restart.
        rounding._inputs.clear()
        await rounding.download(None, USER, Screen.for_user(USER), [first.stem])
        send.assert_awaited_once_with(str(first), kind="file", user_id=USER.max_user_id)
        await rounding.show(None, USER, Screen.for_user(USER))
        assert screens[-1][1][-3][0]["payload"] == f"round:download:{second.stem}"
        assert screens[-1][1][-2][0]["payload"] == "round:reset"


async def test_failed_upload_retries_and_download_is_user_scoped():
    with (
        patch.object(Screen, "show", AsyncMock(return_value="screen")),
        patch.object(rounding.max_api, "download_payload", AsyncMock(return_value=b"broken")),
        patch.object(rounding.max_api, "send_file", AsyncMock()) as send,
    ):
        await rounding.standard(None, USER, Screen.for_user(USER), [])
        await rounding.ingest_images(None, USER, update())
        assert get_wait(USER.max_user_id) == rounding.WAIT_ROUND_IMAGE
        assert rounding._latest(USER) is None
        result = rounding._save(USER, image_bytes(), 300)
        other = User(id=901, max_user_id=901, name="other")
        await rounding.download(None, other, Screen.for_user(other), [result.stem])
        await rounding.download(None, USER, Screen.for_user(USER), ["../../other"])
        send.assert_not_awaited()


async def test_result_disappears_from_menu_and_download_after_ten_minutes():
    result = rounding._save(USER, image_bytes(), 300)
    created = time.time()
    os.utime(result, (created - 599, created - 599))
    assert rounding._latest(USER) == result

    os.utime(result, (created - 601, created - 601))
    with (
        patch.object(Screen, "show", AsyncMock(return_value="screen")) as show,
        patch.object(rounding.max_api, "send_file", AsyncMock()) as send,
    ):
        await rounding.show(None, USER, Screen.for_user(USER))
        assert rounding._latest(USER) is None
        assert not result.exists()
        assert [button["text"] for row in show.await_args.args[1] for button in row] == [
            "Стандартный", "Свой размер", "← Назад"
        ]
        await rounding.download(None, USER, Screen.for_user(USER), [result.stem])
        send.assert_not_awaited()


async def test_reset_restores_original_upload():
    original = image_bytes("JPEG")
    result = rounding._save(USER, original, 300)
    with Image.open(result) as rounded:
        assert rounded.size == (300, 300)
        assert rounded.getpixel((0, 0))[3] == 0
    screens = []

    async def show(self, text, kb, photo=None):
        screens.append((text, [b["text"] for row in kb for b in row],
                        Image.open(photo).copy() if photo else None))
        return "menu"

    with patch.object(Screen, "show", show):
        await rounding.reset(None, USER, Screen.for_user(USER), [])
    restored = rounding._latest(USER)
    with Image.open(restored) as image:
        assert image.size == (200, 100)
        assert image.getpixel((0, 0))[0] > 250
    assert "Сброс" in screens[-1][1]


async def test_rounding_routes_input_cancel_and_start_do_not_apply_watermark():
    async def click(payload):
        await callbacks.handle_message_callback(None, {"callback": {
            "user": {"user_id": USER.max_user_id}, "callback_id": "cb", "payload": payload,
            "message": {"body": {"mid": "menu"}},
        }})

    async def message(text=""):
        event = update(text)
        event["message"]["sender"] = {"user_id": USER.max_user_id}
        event["message"]["recipient"] = {"chat_type": "dialog"}
        await messages.handle_message_created(None, event)

    with (
        patch.object(callbacks.user_repo, "upsert_user", AsyncMock(return_value=USER)),
        patch.object(callbacks, "answer_callback", AsyncMock()),
        patch.object(Screen, "show", AsyncMock(return_value="menu")) as show,
        patch.object(rounding.max_api, "download_payload", AsyncMock(return_value=image_bytes())),
        patch.object(messages, "_apply_items", AsyncMock()) as watermark,
    ):
        await click("round:menu")
        await click("round:custom")
        await message("600 600")
        assert get_wait(USER.max_user_id) == rounding.WAIT_ROUND_IMAGE
        await message()
        assert Image.open(rounding._latest(USER)).size == (600, 600)
        watermark.assert_not_awaited()
        assert get_wait(USER.max_user_id) is None
        await message()
        watermark.assert_awaited_once()
        await click("round:menu")
        assert get_wait(USER.max_user_id) is None
        await click("nav:home")
        assert show.await_args.args[0] == "Главное меню"
        await click("round:standard")
        await message("/start")
        assert get_wait(USER.max_user_id) is None
        assert show.await_args.args[0] == "Главное меню"
