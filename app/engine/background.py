"""Transparent-background images and their checkerboard menu preview."""
from __future__ import annotations

import io
from statistics import median

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps


def remove_background(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as source:
        if source.width * source.height > 25_000_000:
            raise ValueError("Image exceeds 25 megapixels")
        image = ImageOps.exif_transpose(source).convert("RGBA")
    corners_xy = ((0, 0), (image.width - 1, 0), (0, image.height - 1),
                  (image.width - 1, image.height - 1))
    if all(image.getpixel(point)[3] == 0 for point in corners_xy):
        return image
    work = image.convert("RGB")
    # ponytail: cap the flood-fill working set; use native segmentation for fine hair.
    work.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
    w, h = work.size
    corners = [work.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    color = tuple(int(median(c[i] for c in corners)) for i in range(3))
    difference = ImageChops.difference(work, Image.new("RGB", work.size, color))
    r, g, b = difference.split()
    distance = ImageChops.lighter(ImageChops.lighter(r, g), b)
    candidates = distance.point(lambda value: 0 if value <= 30 else 255)
    mask = ImageOps.expand(candidates, 1, fill=0)
    ImageDraw.floodfill(mask, (0, 0), 128)
    mask = mask.crop((1, 1, w + 1, h + 1)).point(lambda value: 0 if value == 128 else 255)
    mask = mask.filter(ImageFilter.GaussianBlur(0.5))
    mask = mask.resize(image.size, Image.Resampling.LANCZOS)
    image.putalpha(ImageChops.multiply(image.getchannel("A"), mask))
    return image


def preview_image(result: Image.Image | None = None) -> Image.Image:
    preview = Image.new("RGB", (560, 560), "white")
    draw = ImageDraw.Draw(preview)
    for y in range(0, 560, 28):
        for x in range(0, 560, 28):
            if (x // 28 + y // 28) % 2 == 0:
                draw.rectangle((x, y, x + 27, y + 27), fill=(100, 100, 100))
    if result is not None:
        image = ImageOps.contain(result.convert("RGBA"), preview.size,
                                 Image.Resampling.LANCZOS)
        preview.paste(image, ((560 - image.width) // 2, (560 - image.height) // 2), image)
    return preview
