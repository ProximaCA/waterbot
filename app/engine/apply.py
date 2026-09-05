"""Apply a template (+ optional tail) to bytes, write under DATA_DIR."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from app.config import DATA_DIR, MAX_TAIL_SECONDS, MAX_VIDEO_SECONDS
from app.engine.image import apply_watermark, save_jpeg
from app.engine.video import (
    VideoRejected,
    concat_sync,
    duration_seconds,
    watermark_video_sync,
)
from app.models import Tail, Template


def user_dir(user_pk: int) -> Path:
    p = DATA_DIR / str(user_pk)
    p.mkdir(parents=True, exist_ok=True)
    return p


def tmp_path(user_pk: int, suffix: str) -> Path:
    return user_dir(user_pk) / f"tmp-{uuid.uuid4().hex}{suffix}"


def store_upload(user_pk: int, data: bytes, suffix: str) -> Path:
    dest = user_dir(user_pk) / f"{uuid.uuid4().hex}{suffix}"
    dest.write_bytes(data)
    return dest


def apply_photo(data: bytes, template: Template, dest: Path) -> Path:
    img = apply_watermark(data, Path(template.file_path), template.overlay())
    return save_jpeg(img, dest)


def apply_video(
    video: Path,
    template: Template,
    dest: Path,
    *,
    tail: Optional[Tail] = None,
) -> Path:
    marked = dest.with_name(dest.stem + "-wm.mp4")
    try:
        watermark_video_sync(
            video,
            Path(template.file_path),
            marked,
            overlay=template.overlay(),
            max_seconds=MAX_VIDEO_SECONDS,
        )
        if not tail:
            marked.replace(dest)
            return dest
        tail_path = Path(tail.file_path)
        if duration_seconds(tail_path) > MAX_TAIL_SECONDS:
            raise VideoRejected(f"хвост длиннее {MAX_TAIL_SECONDS} с")
        if tail.placement == "start":
            concat_sync(tail_path, marked, dest)
        else:
            concat_sync(marked, tail_path, dest)
        return dest
    finally:
        if marked.exists() and marked.resolve() != dest.resolve():
            marked.unlink(missing_ok=True)
