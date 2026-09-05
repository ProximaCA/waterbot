"""Pillow watermark overlay."""
from __future__ import annotations

import io
import random
from pathlib import Path
from typing import Sequence

from PIL import Image

from app.models import Overlay

_PNG = b"\x89PNG\r\n\x1a\n"
_JPEG = b"\xff\xd8\xff"
_GIF87 = b"GIF87a"
_GIF89 = b"GIF89a"


def sniff_image(data: bytes) -> str | None:
    """Return a suffix (`.png`, `.jpg`, …) if *data* is a still image."""
    if len(data) >= 8 and data[:8] == _PNG:
        return ".png"
    if len(data) >= 3 and data[:3] == _JPEG:
        return ".jpg"
    if len(data) >= 6 and data[:6] in (_GIF87, _GIF89):
        return ".gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if len(data) >= 2 and data[:2] == b"BM":
        return ".bmp"
    try:
        fmt = (Image.open(io.BytesIO(data)).format or "").upper()
    except Exception:
        return None
    return {
        "JPEG": ".jpg",
        "PNG": ".png",
        "GIF": ".gif",
        "WEBP": ".webp",
        "BMP": ".bmp",
        "TIFF": ".tif",
        "HEIF": ".heic",
        "HEIC": ".heic",
    }.get(fmt)

GRID = {
    "nw": (0.0, 0.0),
    "n": (0.5, 0.0),
    "ne": (1.0, 0.0),
    "w": (0.0, 0.5),
    "c": (0.5, 0.5),
    "e": (1.0, 0.5),
    "sw": (0.0, 1.0),
    "s": (0.5, 1.0),
    "se": (1.0, 1.0),
}


def _load(src: Path | bytes | Image.Image) -> Image.Image:
    if isinstance(src, Image.Image):
        return src.convert("RGBA")
    if isinstance(src, (bytes, bytearray)):
        return Image.open(io.BytesIO(src)).convert("RGBA")
    return Image.open(src).convert("RGBA")


def _scale_mark(mark: Image.Image, base_w: int, width_pct: int) -> Image.Image:
    target_w = max(1, int(base_w * max(1, min(width_pct, 100)) / 100))
    ratio = target_w / max(1, mark.width)
    target_h = max(1, int(mark.height * ratio))
    return mark.resize((target_w, target_h), Image.Resampling.LANCZOS)


def _apply_opacity(mark: Image.Image, opacity: int) -> Image.Image:
    opacity = max(0, min(100, opacity))
    if opacity >= 100:
        return mark
    r, g, b, a = mark.split()
    a = a.point(lambda p, o=opacity: int(p * o / 100))
    mark = Image.merge("RGBA", (r, g, b, a))
    return mark


def _xy(
    base: tuple[int, int],
    mark: tuple[int, int],
    ax: float,
    ay: float,
    pad_x_pct: int,
    pad_y_pct: int,
) -> tuple[int, int]:
    bw, bh = base
    mw, mh = mark
    pad_x = int(bw * pad_x_pct / 100)
    pad_y = int(bh * pad_y_pct / 100)
    x = int((bw - mw) * ax) + pad_x
    y = int((bh - mh) * ay) + pad_y
    return x, y


def _anchors(
    base: tuple[int, int],
    mark: tuple[int, int],
    position: str,
    pad_x: int,
    pad_y: int,
) -> list[tuple[int, int]]:
    if position == "corners":
        return [
            _xy(base, mark, *GRID[k], pad_x, pad_y) for k in ("nw", "ne", "sw", "se")
        ]
    if position == "random":
        ax, ay = GRID[random.choice(list(GRID))]
        return [_xy(base, mark, ax, ay, pad_x, pad_y)]
    ax, ay = GRID[position]
    return [_xy(base, mark, ax, ay, pad_x, pad_y)]


def render_overlay(
    canvas_size: tuple[int, int],
    mark_src: Path | bytes | Image.Image,
    overlay: Overlay,
    *,
    canvas: Image.Image | None = None,
) -> Image.Image:
    """RGBA canvas with the mark placed. Transparent if *canvas* is omitted."""
    out = (
        canvas.convert("RGBA")
        if canvas is not None
        else Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    )
    mark = _load(mark_src)
    if overlay.position == "fill":
        mark = mark.resize(out.size, Image.Resampling.LANCZOS)
    else:
        mark = _scale_mark(mark, out.width, overlay.width_pct)
    if overlay.rotation_deg:
        mark = mark.rotate(
            overlay.rotation_deg, expand=True, resample=Image.Resampling.BICUBIC
        )
    mark = _apply_opacity(mark, overlay.opacity)
    if overlay.position == "fill":
        out.alpha_composite(mark, (0, 0))
    else:
        for x, y in _anchors(
            out.size, mark.size, overlay.position, overlay.pad_x, overlay.pad_y
        ):
            out.alpha_composite(mark, (x, y))
    return out


def apply_watermark(
    base_src: Path | bytes | Image.Image,
    mark_src: Path | bytes | Image.Image,
    overlay: Overlay,
) -> Image.Image:
    base = _load(base_src)
    over = render_overlay(base.size, mark_src, overlay, canvas=base)
    return over.convert("RGB")


def save_jpeg(img: Image.Image, dest: Path, quality: int = 90) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "JPEG", quality=quality)
    return dest


def jpeg_bytes(img: Image.Image, quality: int = 90) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def contact_sheet(mark_paths: Sequence[Path], *, cell: int = 220, cols: int = 3) -> Image.Image:
    """Dark grid of watermark previews for the templates list."""
    paths = list(mark_paths)
    if not paths:
        img = Image.new("RGB", (cell, cell), (24, 24, 28))
        return img
    n = len(paths)
    cols = max(1, min(cols, n))
    rows = (n + cols - 1) // cols
    canvas = Image.new("RGB", (cols * cell, rows * cell), (24, 24, 28))
    for i, p in enumerate(paths):
        try:
            im = _load(p)
        except Exception:
            continue
        im.thumbnail((cell - 16, cell - 16), Image.Resampling.LANCZOS)
        bg = Image.new("RGBA", (cell, cell), (24, 24, 28, 255))
        x = (cell - im.width) // 2
        y = (cell - im.height) // 2
        bg.alpha_composite(im, (x, y))
        rr, cc = i // cols, i % cols
        canvas.paste(bg.convert("RGB"), (cc * cell, rr * cell))
    return canvas
