from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app.engine.image import GRID, apply_watermark, contact_sheet, jpeg_bytes, pad_chart, render_overlay, sniff_image
from app.models import Overlay, Template


def _png(w=80, h=40, color=(255, 0, 0, 180)) -> bytes:
    im = Image.new("RGBA", (w, h), color)
    buf = BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _base(w=400, h=300, color=(10, 80, 10)) -> bytes:
    im = Image.new("RGB", (w, h), color)
    buf = BytesIO()
    im.save(buf, "JPEG")
    return buf.getvalue()


def test_se_places_mark_in_bottom_right():
    out = apply_watermark(_base(), _png(), Overlay(position="se", width_pct=25, opacity=100))
    px = out.getpixel((out.width - 5, out.height - 5))
    assert px[0] > 80


@pytest.mark.parametrize("size,mark_size,expected", [
    ((1868, 270), (512, 512), (81, 81)),
    ((270, 1868), (512, 512), (81, 81)),
    ((720, 720), (200, 100), (216, 108)),
    ((1920, 1080), (100, 400), (81, 324)),
    ((1080, 1920), (400, 100), (324, 81)),
])
@pytest.mark.parametrize("position", GRID)
def test_mark_fits_source_format_and_selected_position(size, mark_size, expected, position):
    mark = Image.new("RGBA", mark_size, (255, 0, 0, 255))
    out = render_overlay(size, mark, Overlay(position=position, width_pct=30))
    ax, ay = GRID[position]
    w, h = expected
    x, y = int((size[0] - w) * ax), int((size[1] - h) * ay)
    assert out.getchannel("A").getbbox() == (x, y, x + w, y + h)


@pytest.mark.parametrize("rotation", [15, 90])
def test_rotated_mark_fits_short_image(rotation):
    mark = Image.new("RGBA", (100, 400), (255, 0, 0, 255))
    out = render_overlay((1868, 270), mark, Overlay(rotation_deg=rotation, width_pct=30))
    x0, y0, x1, y1 = out.getchannel("A").getbbox()
    assert 0 < x1 - x0 <= 561
    assert 0 < y1 - y0 <= 81
    assert (x1, y1) == out.size


def test_fill_covers_canvas():
    out = apply_watermark(_base(), _png(10, 10, (0, 0, 255, 255)), Overlay(position="fill"))
    assert out.size == (400, 300)
    assert out.getpixel((10, 10))[2] > 80


def test_corners_four_copies():
    out = apply_watermark(
        _base(), _png(40, 20, (255, 255, 0, 255)), Overlay(position="corners", width_pct=10)
    )
    samples = [
        out.getpixel((8, 8)),
        out.getpixel((out.width - 8, 8)),
        out.getpixel((8, out.height - 8)),
        out.getpixel((out.width - 8, out.height - 8)),
    ]
    assert all(p[0] > 80 or p[1] > 80 for p in samples)


def test_contact_sheet_empty():
    img = contact_sheet([])
    assert img.size == (660, 248)
    assert img.getpixel((110, 110)) == (255, 255, 255)


def test_contact_sheet_keeps_empty_slots_and_marks_selection(tmp_path):
    path = tmp_path / "mark.png"
    path.write_bytes(_png(color=(255, 0, 0, 255)))
    img = contact_sheet([None, tmp_path / "missing.png", path], selected_index=2)
    assert img.size == (660, 248)
    assert img.getpixel((110, 110)) == (255, 255, 255)
    assert img.getpixel((330, 110)) == (255, 255, 255)
    assert img.getpixel((550, 110)) == (255, 0, 0)
    assert img.getpixel((443, 110)) == (34, 177, 76)
    assert img.getpixel((3, 110)) == (230, 230, 230)


def test_jpeg_bytes_roundtrip():
    img = apply_watermark(_base(), _png(), Overlay(position="c", width_pct=30))
    blob = jpeg_bytes(img)
    assert blob[:2] == b"\xff\xd8"


def test_sniff_image():
    assert sniff_image(_png()) == ".png"
    assert sniff_image(_base()) == ".jpg"
    assert sniff_image(b"%PDF-1.4") is None
    assert sniff_image(b"") is None


def test_template_overlay():
    t = Template(id=1, user_id=1, name="x", file_path="p.png", position="c", width_pct=40)
    out = apply_watermark(_base(), _png(), t.overlay())
    assert out.size == (400, 300)


def test_pad_chart_places_template_on_xy_axes(tmp_path):
    mark = tmp_path / "mark.png"
    Image.new("RGBA", (40, 40), (255, 0, 0, 255)).save(mark)
    origin = pad_chart(mark, 0, 0)
    right = pad_chart(mark, 20, 0)
    down = pad_chart(mark, 0, 20)
    assert origin.size == right.size == down.size
    cx, cy = origin.size[0] // 2, origin.size[1] // 2
    assert origin.getpixel((cx, cy))[0] > 200
    assert right.getpixel((cx, cy))[0] < 80
    assert right.getpixel((cx + 120, cy))[0] > 200
    assert down.getpixel((cx, cy))[0] < 80
    assert down.getpixel((cx, cy + 120))[0] > 200
    assert origin.getpixel((cx + 80, cy))[0] < 80
    assert origin.getpixel((cx, 12))[0] < 80


def test_opacity_zero_keeps_base():
    out = apply_watermark(
        _base(),
        _png(color=(255, 0, 0, 255)),
        Overlay(position="c", width_pct=50, opacity=0),
    )
    px = out.getpixel((200, 150))
    assert px[0] < 40 and px[1] > 60
