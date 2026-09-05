from io import BytesIO
from pathlib import Path

from PIL import Image

from app.engine.image import apply_watermark, contact_sheet, jpeg_bytes, sniff_image
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
    assert img.size[0] > 0


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


def test_opacity_zero_keeps_base():
    out = apply_watermark(
        _base(),
        _png(color=(255, 0, 0, 255)),
        Overlay(position="c", width_pct=50, opacity=0),
    )
    px = out.getpixel((200, 150))
    assert px[0] < 40 and px[1] > 60
