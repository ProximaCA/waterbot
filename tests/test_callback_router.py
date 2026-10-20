"""Payload prefixes used by the callback router stay unique and parseable."""

import pytest

from app.handlers.message_callback import ROUTES, _as_position, _int, parse_payload


def test_int_helper():
    assert _int("12") == 12
    assert _int("x") is None


def test_as_position_rejects_garbage():
    assert _as_position("se") == "se"
    assert _as_position("corners") == "corners"
    with pytest.raises(ValueError):
        _as_position("nope")


def test_parse_payload():
    assert parse_payload("") == ("", [])
    assert parse_payload("tab:tpl") == ("tab:tpl", [])
    assert parse_payload("tpl:open:4") == ("tpl:open", ["4"])
    assert parse_payload("wm:setpos:9:corners") == ("wm:setpos", ["9", "corners"])
    assert parse_payload("ch:tpl:2:0") == ("ch:tpl", ["2", "0"])
    assert parse_payload("tail:place:1:end") == ("tail:place", ["1", "end"])
    assert parse_payload("wm:px:3") == ("wm:px", ["3"])


def test_routes_cover_parsed_keys():
    from app.keyboards.builders import (
        cancel_channel_wait_kb,
        cancel_tail_wait_kb,
        cancel_wait_kb,
        channel_card_kb,
        channels_list_kb,
        confirm_delete_tail_kb,
        confirm_delete_tpl_kb,
        opacity_kb,
        pad_kb,
        position_kb,
        rotation_kb,
        tail_card_kb,
        tails_list_kb,
        tabs_kb,
        template_card_kb,
        templates_list_kb,
        width_kb,
    )
    from app.models import Channel, Tail, Template

    tpl = Template(id=4, user_id=1, name="x", file_path="p.png", is_default=True)
    tail = Tail(id=1, user_id=1, name="t", file_path="v.mp4")
    ch = Channel(id=2, user_id=1, chat_id=99, title="c")
    kbs = [
        tabs_kb(""),
        templates_list_kb([tpl]),
        template_card_kb(tpl),
        confirm_delete_tpl_kb(4),
        position_kb(4, tpl.position),
        width_kb(4),
        opacity_kb(4),
        rotation_kb(4),
        pad_kb(4, "x"),
        pad_kb(4, "y"),
        cancel_wait_kb(),
        tails_list_kb([tail], True),
        tail_card_kb(tail),
        confirm_delete_tail_kb(1),
        cancel_tail_wait_kb(),
        channels_list_kb([ch]),
        channel_card_kb(ch, [tpl]),
        cancel_channel_wait_kb(),
    ]
    payloads = [b["payload"] for kb in kbs for row in kb for b in row]
    for raw in payloads:
        key, _args = parse_payload(raw)
        assert key in ROUTES, raw
    assert parse_payload("ch:tpl:2:0") == ("ch:tpl", ["2", "0"])
    assert parse_payload("wm:setrot:1:-15") == ("wm:setrot", ["1", "-15"])
