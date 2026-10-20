"""Pillow watermark overlay."""
from __future__ import annotations

import io
import random
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw

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


def _scale_mark(mark: Image.Image, base: tuple[int, int], width_pct: int) -> Image.Image:
    ratio = min(base[0] / mark.width, base[1] / mark.height)
    ratio *= max(1, min(width_pct, 100)) / 100
    target_w = max(1, round(mark.width * ratio))
    target_h = max(1, round(mark.height * ratio))
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
    if overlay.rotation_deg:
        mark = mark.rotate(
            overlay.rotation_deg, expand=True, resample=Image.Resampling.BICUBIC
        )
    if overlay.position != "fill":
        mark = _scale_mark(mark, out.size, overlay.width_pct)
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


_CHART = 400
_PAD_PX = 6  # 20% pad → 120px from center


def pad_chart(mark_src: Path | bytes | Image.Image, pad_x: int, pad_y: int) -> Image.Image:
    """Square XY graph: origin at center, +X right, +Y down, mini-template at pad."""
    size = _CHART
    cx = cy = size // 2
    canvas = Image.new("RGB", (size, size), (236, 240, 244))
    draw = ImageDraw.Draw(canvas)
    axis = (40, 48, 56)
    draw.line((0, cy, size - 1, cy), fill=axis, width=2)
    draw.line((cx, 0, cx, size - 1), fill=axis, width=2)
    for tick in (-20, -10, 10, 20):
        d = tick * _PAD_PX
        draw.line((cx + d, cy - 6, cx + d, cy + 6), fill=axis, width=2)
        draw.line((cx - 6, cy + d, cx + 6, cy + d), fill=axis, width=2)
    draw.text((size - 22, cy + 8), "X", fill=axis, font_size=18)
    draw.text((cx + 8, size - 28), "Y", fill=axis, font_size=18)
    mark = _load(mark_src)
    mark.thumbnail((72, 72), Image.Resampling.LANCZOS)
    x = cx + pad_x * _PAD_PX - mark.width // 2
    y = cy + pad_y * _PAD_PX - mark.height // 2
    canvas.paste(mark, (x, y), mark)
    return canvas


def contact_sheet(
    mark_paths: Sequence[Path | None], *, cell: int = 220, cols: int = 3,
    selected_index: int | None = None,
) -> Image.Image:
    """White template slots, with a green outline around the active watermark."""
    paths = list(mark_paths)
    n = max(cols, len(paths))
    rows = (n + cols - 1) // cols
    canvas = Image.new("RGB", (cols * cell, rows * (cell + 28)), "white")
    draw = ImageDraw.Draw(canvas)
    for i in range(n):
        rr, cc = i // cols, i % cols
        left, top = cc * cell, rr * (cell + 28)
        p = paths[i] if i < len(paths) else None
        if p is not None:
            try:
                im = _load(p)
            except Exception:
                im = None
            if im is not None:
                im.thumbnail((cell - 24, cell - 24), Image.Resampling.LANCZOS)
                canvas.paste(im, (left + (cell - im.width) // 2,
                                  top + (cell - im.height) // 2), im)
        draw.rectangle(
            (left + 3, top + 3, left + cell - 4, top + cell - 4),
            outline=(34, 177, 76) if i == selected_index else (230, 230, 230),
            width=4 if i == selected_index else 1,
        )
        draw.text((left + cell // 2, top + cell + 3), str(i + 1),
                  fill="black", anchor="mt", font_size=18)
    return canvas
