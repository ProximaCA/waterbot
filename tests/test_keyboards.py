import pytest

from app.keyboards.builders import (
    POSITIONS_GRID,
    channel_card_kb,
    channels_list_kb,
    confirm_delete_tpl_kb,
    position_kb,
    profile_kb,
    tabs_kb,
    tail_card_kb,
    tails_list_kb,
    template_card_kb,
    templates_list_kb,
    width_kb,
)
from app.models import Channel, Tail, Template


def _payloads(kb):
    return [b["payload"] for row in kb for b in row]


def _tpl(**kw) -> Template:
    data = dict(id=1, user_id=1, name="x", file_path="p.png", is_default=False)
    data.update(kw)
    return Template(**data)


def test_tabs_mark_active_once():
    kb = tabs_kb("tpl")
    texts = [b["text"] for row in kb for b in row]
    assert texts.count("✅ 🖼 Шаблоны") == 1
    assert "✅ 〽️ Хвосты" not in texts
    assert _payloads(kb) == ["tab:tpl", "tab:tails", "round:menu", "bg:menu", "tab:ch", "tab:me"]
    assert [[b["text"] for b in row] for row in tabs_kb("")] == [
        ["🖼 Шаблоны", "〽️ Хвосты"], ["🌝 Округление", "◻️ Убрать фон"],
        ["🤖 Авто замена в канале"], ["👤 Профиль"],
    ]


def test_templates_list_has_three_fixed_slots():
    empty = templates_list_kb([])
    assert [row[0]["text"] for row in empty] == [
        "➕ Добавить шаблон 1", "➕ Добавить шаблон 2", "➕ Добавить шаблон 3", "⬅️ Назад"
    ]
    kb = templates_list_kb([_tpl(id=9, slot=3, is_default=True)])
    assert _payloads(kb) == [
        "tpl:new:1", "tpl:new:2", "tpl:select:9", "tpl:open:9", "tpl:back"
    ]
    assert [b["text"] for b in kb[2]] == ["✅ 3", "⚙️ Редактировать"]
    full = templates_list_kb([_tpl(id=i, slot=i) for i in range(1, 4)])
    assert [row[0]["text"] for row in full[:3]] == ["☑️ 1", "☑️ 2", "☑️ 3"]
    assert not any(p.startswith("tpl:new") for p in _payloads(full))


def test_pickers_have_back_to_card_and_no_tabs():
    kb = position_kb(9, "se")
    payloads = _payloads(kb)
    assert "tpl:open:9" in payloads
    assert "tab:tpl" not in payloads
    assert any(p.endswith(":se") for p in payloads)
    assert [[b["text"] for b in row] for row in kb] == [
        ["↖️", "⬆️", "↗️"], ["⬅️", "⏹️", "➡️"], ["↙️", "⬇️", "❎"], ["⬅️ Назад"]
    ]
    w = _payloads(width_kb(9))
    assert w[-1] == "tpl:open:9"
    assert "tab:ch" not in w


@pytest.mark.parametrize("position", [code for _, code in POSITIONS_GRID])
def test_position_marks_only_the_selected_cell(position):
    kb = position_kb(9, position)
    selected = [b for row in kb for b in row if b["text"] == "❎"]
    assert len(selected) == 1
    assert selected[0]["payload"] == f"wm:setpos:9:{position}"


def test_card_back_is_templates_root():
    t = _tpl(id=4, is_default=True)
    payloads = _payloads(template_card_kb(t))
    assert payloads.count("tab:tpl") == 1
    assert [p for p in payloads if p.startswith("tab:")] == ["tab:tpl"]
    assert payloads[-1] == "tab:tpl"
    assert "wm:pos:4" in payloads
    assert "tpl:del:4" in payloads
    assert [[b["text"] for b in row] for row in template_card_kb(t)][3] == [
        "Округлить", "Убрать фон"
    ]
    assert "tpl:round:4" in payloads
    assert "tpl:bg:4" in payloads


def test_channel_card_back_to_list():
    c = Channel(id=2, user_id=1, chat_id=99, title="ch", enabled=True)
    payloads = _payloads(channel_card_kb(c, [_tpl(id=1)]))
    assert [p for p in payloads if p.startswith("tab:")] == ["tab:ch"]
    assert payloads[-1] == "tab:ch"
    assert "ch:unbind:2" in payloads
    assert "ch:tpl:2:0" in payloads
    assert "ch:tail:2" in payloads
    assert "ch:toggle:2" in payloads


def test_channel_template_labels_follow_fixed_slots_and_selection():
    c = Channel(id=2, user_id=1, chat_id=99, title="ch", template_id=9)
    kb = channel_card_kb(c, [_tpl(id=9, slot=3), _tpl(id=8, slot=2)])
    labels = {b["payload"]: b["text"] for row in kb for b in row}
    assert labels["ch:tpl:2:9"] == "✅ Шаблон 3"
    assert labels["ch:tpl:2:8"] == "☑️ Шаблон 2"
    assert labels["ch:tpl:2:0"] == "☑️ Активный из «Шаблоны»"


def test_channel_enabled_and_disabled_marks_match_controls():
    for enabled, mark in [(True, "✅"), (False, "⛔️")]:
        c = Channel(id=2, user_id=1, chat_id=99, title="Канал", enabled=enabled, use_tail=enabled)
        listed = next(b for row in channels_list_kb([c]) for b in row if b["payload"] == "ch:open:2")
        assert listed["text"] == f"{mark} Канал"
        kb = channel_card_kb(c, [])
        assert kb[0][0]["text"] == f"{mark} Автозамена"
        assert kb[1][0]["text"] == f"{mark} Хвост для видео"


def test_profile_kb_returns_to_main_menu():
    kb = profile_kb()
    texts = [b["text"] for row in kb for b in row]
    payloads = _payloads(kb)
    assert payloads == ["nav:home"]
    assert texts == ["⬅️ Назад"]
    assert all("оплат" not in t.lower() and "звезд" not in t.lower() for t in texts)


def test_section_roots_return_to_menu_and_tail_card_to_list():
    for kb in (tails_list_kb([], False), channels_list_kb([])):
        assert _payloads(kb)[-1] == "nav:home"
        assert kb[-1][0]["text"] == "⬅️ Назад"
        assert not any(p.startswith("tab:") for p in _payloads(kb))
    tail = Tail(id=2, user_id=1, name="tail", file_path="v.mp4")
    payloads = _payloads(tail_card_kb(tail))
    assert [p for p in payloads if p.startswith("tab:")] == ["tab:tails"]
    assert payloads[-1] == "tab:tails"


def test_confirm_delete_has_no_tabs():
    payloads = _payloads(confirm_delete_tpl_kb(3))
    assert payloads == ["tpl:delok:3", "tpl:open:3"]
    assert "tab:tpl" not in payloads
