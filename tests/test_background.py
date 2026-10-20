import io
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from app.engine import apply, background as engine
from app.handlers import background, message_callback as callbacks, message_created as messages
from app.models import User
from app.renderers.views import Screen
from app.wait import clear_wait, get_wait

USER = User(id=910, max_user_id=910, name="background")


def update(*, file=False):
    return {"message": {"sender": {"user_id": USER.max_user_id},
        "recipient": {"chat_type": "dialog"}, "body": {"attachments": [{
            "type": "file" if file else "image", "payload": {"token": "photo", "filename": "photo.png"},
        }]}}}


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(apply, "DATA_DIR", tmp_path)
    yield
    clear_wait(USER.max_user_id)
    background._inputs.clear()
    background._locks.clear()


async def test_menu_upload_download_and_next_photo_uses_active_template(monkeypatch):
    result = Image.new("RGBA", (200, 100), (10, 20, 30, 255))
    result.putpixel((0, 0), (0, 0, 0, 0))
    monkeypatch.setattr(engine, "remove_background", lambda data: result, raising=False)
    screens = []
    async def show(self, text, kb, photo=None):
        screens.append((text, kb, Image.open(photo).copy() if photo else None))
        return str(len(screens))
    async def click(payload):
        await callbacks.handle_message_callback(None, {"callback": {
            "user": {"user_id": USER.max_user_id}, "callback_id": "callback", "payload": payload,
            "message": {"body": {"mid": "menu"}},
        }})
    with (
        patch.object(callbacks.user_repo, "upsert_user", AsyncMock(return_value=USER)),
        patch.object(callbacks, "answer_callback", AsyncMock()),
        patch.object(Screen, "show", show),
        patch.object(background.max_api, "download_payload", AsyncMock(return_value=b"image")),
        patch.object(background.max_api, "send_file", AsyncMock()) as send,
        patch.object(messages, "_apply_items", AsyncMock()) as watermark,
    ):
        await click("bg:menu")
        assert screens[-1][0] == "◻️ **Убрать фон**\n\nЗагрузите изображение, мы удалим фон и сохраним главное."
        assert [b["text"] for row in screens[-1][1] for b in row] == [
            "➕ Загрузить", "← Назад"
        ]
        assert screens[-1][2].getpixel((10, 10)) != screens[-1][2].getpixel((40, 10))
        for as_file in (False, True):
            await click("bg:upload")
            assert screens[-1][0] == "ℹ️ Загрузите изображения формата PNG.\n\n" + background.PNG_FILE_NOTE
            await messages.handle_message_created(None, update(file=as_file))
            assert screens[-2][0] == "🔄 **Обрабатываем изображение..**"
            assert screens[-1][0] == background.BODY
            assert get_wait(USER.max_user_id) is None
        watermark.assert_not_awaited()
        ready = background._latest(USER)
        with Image.open(ready) as png:
            assert png.format == "PNG" and png.size == (200, 100)
            assert png.getpixel((0, 0))[3] == 0
        await click(f"bg:download:{ready.stem}")
        send.assert_awaited_once_with(str(ready), kind="file", user_id=USER.max_user_id)
        await messages.handle_message_created(None, update())
        watermark.assert_awaited_once()
        await click("bg:upload")
        await click("nav:home")
        assert get_wait(USER.max_user_id) is None
        assert screens[-1][0] == "Главное меню"


async def test_bad_image_retries_and_other_users_cannot_download(monkeypatch):
    def invalid(data):
        raise ValueError("bad image")
    monkeypatch.setattr(engine, "remove_background", invalid, raising=False)
    with (
        patch.object(Screen, "show", AsyncMock(return_value="retry")),
        patch.object(background.max_api, "download_payload", AsyncMock(return_value=b"broken")),
        patch.object(background.max_api, "send_file", AsyncMock()) as send,
    ):
        await background.upload(None, USER, Screen.for_user(USER), [])
        await background.ingest_images(None, USER, update())
        assert get_wait(USER.max_user_id) == background.WAIT_BG_IMAGE
        assert background._latest(USER) is None
        monkeypatch.setattr(engine, "remove_background", lambda data: Image.new("RGBA", (10, 10)))
        result = background._save(USER, b"image")
        other = User(id=911, max_user_id=911, name="other")
        await background.download(None, other, Screen.for_user(other), [result.stem])
        await background.download(None, USER, Screen.for_user(USER), ["../../private"])
        send.assert_not_awaited()


def test_solid_background_removed_without_erasing_light_details():
    from PIL import ImageDraw
    for background_color, fmt in (("white", "PNG"), ("lime", "JPEG")):
        image = Image.new("RGB", (320, 180), background_color)
        draw = ImageDraw.Draw(image)
        draw.rectangle((90, 30, 230, 150), fill="blue")
        draw.rectangle((120, 70, 180, 110), fill=background_color)
        blob = io.BytesIO()
        image.save(blob, fmt)
        result = engine.remove_background(blob.getvalue())
        assert result.size == image.size and result.mode == "RGBA"
        assert result.getpixel((0, 0))[3] == 0
        assert result.getpixel((319, 179))[3] == 0
        assert result.getpixel((150, 90))[3] == 255
        assert result.getpixel((100, 50))[3] == 255
        preview = engine.preview_image(result)
        assert preview.mode == "RGB"
    transparent = Image.new("RGBA", (80, 80), (255, 255, 255, 0))
    ImageDraw.Draw(transparent).rectangle((20, 20, 60, 60), fill=(10, 20, 30, 150))
    blob = io.BytesIO()
    transparent.save(blob, "PNG")
    assert engine.remove_background(blob.getvalue()).getpixel((40, 40))[3] == 150
    ImageDraw.Draw(transparent).rectangle((20, 20, 60, 60), fill="black")
    blob = io.BytesIO()
    transparent.save(blob, "PNG")
    assert engine.remove_background(blob.getvalue()).getpixel((20, 40)) == (0, 0, 0, 255)
    with pytest.raises(Exception):
        engine.remove_background(b"not an image")
