from unittest.mock import AsyncMock

from PIL import Image

from app.models import Channel, Template, User
from app.renderers import views


async def test_card_links_channel_and_identifies_active_slot(monkeypatch):
    templates = [Template(id=8, user_id=5, name="mark", file_path="p", slot=2, is_default=True)]
    monkeypatch.setattr(views.tpl_repo, "list_for", AsyncMock(return_value=templates))
    monkeypatch.setattr(views, "get_chat", AsyncMock(return_value={
        "link": "https://max.ru/join/example",
    }), raising=False)
    ui = AsyncMock()
    await views.show_channel_card(None, User(5, 100, "test"), Channel(1, 5, 99, "Канал"), ui)
    body = ui.show.await_args.args[0]
    assert "[Канал](https://max.ru/join/example)" in body
    assert "Активный из «Шаблоны» — №2" in body


async def test_channel_preview_tracks_fixed_or_active_template(tmp_path, monkeypatch):
    first, second = tmp_path / "first.png", tmp_path / "second.png"
    Image.new("RGBA", (30, 30), "red").save(first)
    Image.new("RGBA", (30, 30), "blue").save(second)
    templates = [
        Template(4, 5, "first", str(first), slot=1),
        Template(8, 5, "second", str(second), slot=2, is_default=True),
    ]
    monkeypatch.setattr(views.tpl_repo, "list_for", AsyncMock(return_value=templates))
    monkeypatch.setattr(views, "get_chat", AsyncMock(return_value={}))
    for template_id, expected in [(4, first), (8, second), (None, second)]:
        ui = AsyncMock()
        await views.show_channel_card(None, User(5, 100, "test"),
                                      Channel(1, 5, 99, "Канал", template_id=template_id), ui)
        assert ui.show.await_args.args[2] == expected
        assert expected.is_file()
