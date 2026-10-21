"""Pure keyboard factories. Payload: verb:args, origin on the last segment when needed."""
from __future__ import annotations

from typing import Iterable, List, Sequence

from app.models import Channel, Overlay, Tail, Template

BTN_BACK = "← Назад"
_DEFAULT = Overlay()
_PAD_STEP = 10
_PAD_LIMIT = 20


def btn(text: str, payload: str) -> dict:
    return {"type": "callback", "text": text, "payload": payload}


POSITIONS_GRID = (
    ("↖️", "nw"),
    ("⬆️", "n"),
    ("↗️", "ne"),
    ("⬅️", "w"),
    ("⏹️", "c"),
    ("➡️", "e"),
    ("↙️", "sw"),
    ("⬇️", "s"),
    ("↘️", "se"),
)

POSITION_LABELS = {
    "nw": "северо-запад",
    "n": "север",
    "ne": "северо-восток",
    "w": "запад",
    "c": "центр",
    "e": "восток",
    "sw": "юго-запад",
    "s": "юг",
    "se": "юго-восток",
    "corners": "по углам",
    "fill": "залить",
    "random": "случайно",
}

WIDTHS = (5, 10, 15, 20, 25, 30, 40, 50, 60, 75, 100)
OPACITIES = (20, 40, 60, 80, 100)
ROTATIONS = (0, 90, 180, 270, -15, 15)


def tabs_kb(active: str) -> List[List[dict]]:
    def mark(key: str, label: str) -> str:
        return f"✅ {label}" if active == key else label

    return [
        [
            btn(mark("tpl", "🖼 Шаблоны"), "tab:tpl"),
            btn(mark("tails", "〽️ Хвосты"), "tab:tails"),
        ],
        [
            btn(mark("round", "🌝 Округление"), "round:menu"),
            btn("◻️ Убрать фон", "bg:menu"),
        ],
        [btn(mark("ch", "🤖 Авто замена в канале"), "tab:ch")],
        [btn(mark("me", "👤 Профиль"), "tab:me")],
    ]


def templates_list_kb(templates: Sequence[Template]) -> List[List[dict]]:
    kb: List[List[dict]] = []
    by_slot = {t.slot: t for t in templates}
    for i in range(1, max([3, *by_slot]) + 1):
        t = by_slot.get(i)
        if t is None:
            kb.append([btn(f"➕ Добавить шаблон {i}", f"tpl:new:{i}")])
            continue
        check = "✅" if t.is_default else "☑️"
        kb.append(
            [
                btn(f"{check} {i}", f"tpl:select:{t.id}"),
                btn("⚙️ Редактировать", f"tpl:open:{t.id}"),
            ]
        )
    kb.append([btn(BTN_BACK, "tpl:back")])
    return kb


def template_card_kb(t: Template) -> List[List[dict]]:
    tid = t.id
    return [
        [btn("Расположение", f"wm:pos:{tid}"), btn("Ширина", f"wm:w:{tid}")],
        [btn("Прозрачность", f"wm:op:{tid}"), btn("Поворот", f"wm:rot:{tid}")],
        [btn("Сдвиг по X", f"wm:px:{tid}"), btn("Сдвиг по Y", f"wm:py:{tid}")],
        [btn("Округлить", f"tpl:round:{tid}"), btn("Убрать фон", f"tpl:bg:{tid}")],
        [btn("Сброс", f"tpl:reset:{tid}")],
        [btn("Удалить", f"tpl:del:{tid}")],
        [btn(BTN_BACK, "tab:tpl")],
    ]


def confirm_delete_tpl_kb(tid: int) -> List[List[dict]]:
    return [
        [btn("Удалить", f"tpl:delok:{tid}"), btn("Отмена", f"tpl:open:{tid}")],
    ]


def position_kb(tid: int, position: str) -> List[List[dict]]:
    rows: List[List[dict]] = []
    grid = list(POSITIONS_GRID)
    for i in range(0, 9, 3):
        chunk = grid[i : i + 3]
        rows.append([
            btn("❎" if code == position else label, f"wm:setpos:{tid}:{code}")
            for label, code in chunk
        ])
    rows.append([btn("Сброс", f"wm:setpos:{tid}:{_DEFAULT.position}")])
    rows.append([btn(BTN_BACK, f"tpl:open:{tid}")])
    return rows


def _chunk_btns(items: Iterable[tuple[str, str]], per_row: int) -> List[List[dict]]:
    buf = list(items)
    rows: List[List[dict]] = []
    for i in range(0, len(buf), per_row):
        rows.append([btn(t, p) for t, p in buf[i : i + per_row]])
    return rows


def _picked(label: str, current, value) -> str:
    return f"✅ {label}" if current == value else label


def width_kb(tid: int, current: int) -> List[List[dict]]:
    items = [(_picked(f"{n}%", current, n), f"wm:setw:{tid}:{n}") for n in WIDTHS]
    rows = _chunk_btns(items, 4)
    rows.append([btn("Сброс", f"wm:setw:{tid}:{_DEFAULT.width_pct}")])
    rows.append([btn(BTN_BACK, f"tpl:open:{tid}")])
    return rows


def opacity_kb(tid: int, current: int) -> List[List[dict]]:
    items = [(_picked(f"{n}%", current, n), f"wm:setop:{tid}:{n}") for n in OPACITIES]
    rows = _chunk_btns(items, 5)
    rows.append([btn("Сброс", f"wm:setop:{tid}:{_DEFAULT.opacity}")])
    rows.append([btn(BTN_BACK, f"tpl:open:{tid}")])
    return rows


def rotation_kb(tid: int, current: int) -> List[List[dict]]:
    items = [(_picked(f"{n}°", current, n), f"wm:setrot:{tid}:{n}") for n in ROTATIONS]
    rows = _chunk_btns(items, 3)
    rows.append([btn("Сброс", f"wm:setrot:{tid}:{_DEFAULT.rotation_deg}")])
    rows.append([btn(BTN_BACK, f"tpl:open:{tid}")])
    return rows


def pad_kb(tid: int, axis: str, current: int) -> List[List[dict]]:
    verb = "setpx" if axis == "x" else "setpy"
    lo = max(-_PAD_LIMIT, current - _PAD_STEP)
    hi = min(_PAD_LIMIT, current + _PAD_STEP)
    left, right = ("⬅️", "➡️") if axis == "x" else ("⬆️", "⬇️")
    return [
        [
            btn(left, f"wm:{verb}:{tid}:{lo}"),
            btn("Сброс", f"wm:{verb}:{tid}:0"),
            btn(right, f"wm:{verb}:{tid}:{hi}"),
        ],
        [btn(BTN_BACK, f"tpl:open:{tid}")],
    ]


def cancel_wait_kb() -> List[List[dict]]:
    return [[btn(BTN_BACK, "tab:tpl")]]


def tails_list_kb(tails: Sequence[Tail], enabled: bool) -> List[List[dict]]:
    off_mark = "✅ " if not enabled else "☑️ "
    kb: List[List[dict]] = [[btn(f"{off_mark}Не использовать", "tail:off")]]
    kb.append([btn("+ Новый видеохвостик", "tail:new")])
    for t in tails:
        check = "✅" if enabled and t.is_default else "☑️"
        kb.append(
            [
                btn(f"{check} {t.name}", f"tail:use:{t.id}"),
                btn("✎", f"tail:open:{t.id}"),
            ]
        )
    kb.append([btn(BTN_BACK, "nav:home")])
    return kb


def tail_card_kb(t: Tail) -> List[List[dict]]:
    tid = t.id
    start_m = "✅ " if t.placement == "start" else "☑️ "
    end_m = "✅ " if t.placement == "end" else "☑️ "
    use_label = "✅ В работе" if t.is_default else "Сделать основным"
    kb = [
        [
            btn(f"{start_m}В начало", f"tail:place:{tid}:start"),
            btn(f"{end_m}В конец", f"tail:place:{tid}:end"),
        ],
        [btn(use_label, f"tail:use:{tid}"), btn("Удалить", f"tail:del:{tid}")],
        [btn(BTN_BACK, "tab:tails")],
    ]
    return kb


def confirm_delete_tail_kb(tid: int) -> List[List[dict]]:
    return [
        [btn("Удалить", f"tail:delok:{tid}"), btn("Отмена", f"tail:open:{tid}")],
    ]


def cancel_tail_wait_kb() -> List[List[dict]]:
    return [[btn(BTN_BACK, "tab:tails")]]


def channels_list_kb(channels: Sequence[Channel], *, back: str = "nav:home") -> List[List[dict]]:
    kb: List[List[dict]] = [[btn("+ Канал", "ch:add")]]
    for c in channels:
        mark = "✅ " if c.enabled else "⛔️ "
        title = (c.title or str(c.chat_id))[:28]
        kb.append([btn(f"{mark}{title}", f"ch:open:{c.id}")])
    kb.append([btn(BTN_BACK, back)])
    return kb


def channel_card_kb(c: Channel, templates: Sequence[Template]) -> List[List[dict]]:
    cid = c.id
    on_label = "✅ Автозамена" if c.enabled else "⛔️ Автозамена"
    tail_label = "✅ Хвост для видео" if c.use_tail else "⛔️ Хвост для видео"
    kb: List[List[dict]] = [
        [btn(on_label, f"ch:toggle:{cid}")], [btn(tail_label, f"ch:tail:{cid}")]
    ]
    mark = "✅" if c.template_id is None else "☑️"
    kb.append([btn(f"{mark} Активный из «Шаблоны»", f"ch:tpl:{cid}:0")])
    tpl_rows = []
    for t in sorted(templates, key=lambda t: t.slot):
        mark = "✅" if c.template_id == t.id else "☑️"
        tpl_rows.append(btn(f"{mark} Шаблон {t.slot}", f"ch:tpl:{cid}:{t.id}"))
    if tpl_rows:
        kb.append(tpl_rows)
    kb.append([btn("Отвязать", f"ch:unbind:{cid}")])
    kb.append([btn(BTN_BACK, "tab:ch")])
    return kb


def cancel_channel_wait_kb() -> List[List[dict]]:
    return [[btn(BTN_BACK, "tab:ch")]]


def profile_kb() -> List[List[dict]]:
    return [[btn(BTN_BACK, "nav:home")]]


def no_template_kb() -> List[List[dict]]:
    return [[btn("К шаблонам", "tab:tpl")]]
