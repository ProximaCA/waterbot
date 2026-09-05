from app.keyboards.builders import (
    channel_card_kb,
    confirm_delete_tpl_kb,
    position_kb,
    profile_kb,
    tabs_kb,
    template_card_kb,
    templates_list_kb,
    width_kb,
)
from app.models import Channel, Template


def _payloads(kb):
    return [b["payload"] for row in kb for b in row]


def _tpl(**kw) -> Template:
    data = dict(id=1, user_id=1, name="x", file_path="p.png", is_default=False)
    data.update(kw)
    return Template(**data)


def test_tabs_mark_active_once():
    kb = tabs_kb("tpl")
    texts = [b["text"] for row in kb for b in row]
    assert texts.count("✓ Шаблоны") == 1
    assert "✓ Хвосты" not in texts
    assert _payloads(kb) == ["tab:tpl", "tab:tails", "tab:ch", "tab:me"]


def test_templates_list_no_duplicate_new():
    kb = templates_list_kb([_tpl(id=1, is_default=True)])
    payloads = _payloads(kb)
    assert payloads.count("tpl:new") == 1
    assert "tpl:use:1" in payloads
    assert "tpl:open:1" in payloads
    assert payloads[-4:] == ["tab:tpl", "tab:tails", "tab:ch", "tab:me"]


def test_pickers_have_back_to_card_and_no_tabs():
    kb = position_kb(9)
    payloads = _payloads(kb)
    assert "tpl:open:9" in payloads
    assert "tab:tpl" not in payloads
    assert any(p.endswith(":se") for p in payloads)
    assert any(p.endswith(":corners") for p in payloads)
    w = _payloads(width_kb(9))
    assert w[-1] == "tpl:open:9"
    assert "tab:ch" not in w


def test_card_back_is_templates_root():
    t = _tpl(id=4, is_default=True)
    payloads = _payloads(template_card_kb(t))
    # «← Назад» и вкладка «Шаблоны» ведут в один список — как на карточке Telegram.
    assert payloads.count("tab:tpl") == 2
    assert "wm:pos:4" in payloads
    assert "tpl:del:4" in payloads


def test_channel_card_back_to_list():
    c = Channel(id=2, user_id=1, chat_id=99, title="ch", enabled=True)
    payloads = _payloads(channel_card_kb(c, [_tpl(id=1)]))
    assert "tab:ch" in payloads
    assert "ch:unbind:2" in payloads
    assert "ch:tpl:2:0" in payloads
    assert "ch:tail:2" in payloads
    assert "ch:toggle:2" in payloads


def test_profile_kb_is_tabs_only_no_pay():
    kb = profile_kb()
    texts = [b["text"] for row in kb for b in row]
    payloads = _payloads(kb)
    assert payloads == ["tab:tpl", "tab:tails", "tab:ch", "tab:me"]
    assert all("оплат" not in t.lower() and "звезд" not in t.lower() for t in texts)


def test_confirm_delete_has_no_tabs():
    payloads = _payloads(confirm_delete_tpl_kb(3))
    assert payloads == ["tpl:delok:3", "tpl:open:3"]
    assert "tab:tpl" not in payloads
