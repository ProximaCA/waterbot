"""Centered circular PNGs and their menu preview."""
from __future__ import annotations

import io
import re

from PIL import Image, ImageChops, ImageDraw, ImageOps

DEFAULT_SIZE = 1254
MAX_SIZE = 4096


def parse_size(text: str) -> int:
    match = re.fullmatch(r"\s*([0-9]{1,4})\s*(?:[xх×]\s*|\s)([0-9]{1,4})\s*", text, re.I)
    if not match:
        raise ValueError("Укажите размер в формате 600 600 или 300x300.")
    width, height = map(int, match.groups())
    if width != height:
        raise ValueError("Ширина и высота должны быть одинаковыми.")
    if not 1 <= width <= MAX_SIZE:
        raise ValueError(f"Размер должен быть от 1 до {MAX_SIZE} пикселей.")
    return width


def round_image(data: bytes, size: int) -> Image.Image:
    if not 1 <= size <= MAX_SIZE:
        raise ValueError("Invalid output size")
    with Image.open(io.BytesIO(data)) as source:
        if source.width * source.height > 25_000_000:
            raise ValueError("Изображение слишком большое: максимум 25 мегапикселей.")
        source = ImageOps.exif_transpose(source).convert("RGBA")
        result = ImageOps.fit(source, (size, size), Image.Resampling.LANCZOS,
                              centering=(0.5, 0.5))
    mask = Image.new("L", (size * 2, size * 2), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 2 - 1, size * 2 - 1), fill=255)
    mask = mask.resize((size, size), Image.Resampling.LANCZOS)
    result.putalpha(ImageChops.multiply(result.getchannel("A"), mask))
    return result


def preview_image(result: Image.Image | None = None, size: int = DEFAULT_SIZE) -> Image.Image:
    preview = Image.new("RGB", (560, 590), "white")
    draw = ImageDraw.Draw(preview)
    for left in (199, 295):
        draw.rounded_rectangle((left, 12, left + 64, 50), radius=2,
                               outline=(210, 210, 210))
        draw.text((left + 32, 30), str(size), fill=(75, 75, 75),
                  anchor="mm", font_size=16)
    draw.text((280, 30), "x", fill=(75, 75, 75), anchor="mm", font_size=16)
    draw.rectangle((30, 70, 529, 569), fill=(246, 246, 246), outline=(215, 215, 215))
    draw.ellipse((30, 70, 529, 569), fill="white", outline=(180, 180, 180), width=2)
    if result is not None:
        image = result.convert("RGBA").resize((500, 500), Image.Resampling.LANCZOS)
        preview.paste(image, (30, 70), image)
    for x, y in ((30, 70), (529, 70), (30, 569), (529, 569)):
        draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill="white", outline=(150, 150, 150))
    return preview
