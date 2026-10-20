"""ffmpeg overlay + concat. Runs in a thread with a process-wide semaphore."""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.config import FFMPEG_CONCURRENCY, MAX_VIDEO_SECONDS
from app.models import Overlay

_sem = asyncio.Semaphore(max(1, FFMPEG_CONCURRENCY))
_NORMALIZE_FILTER = (
    "scale=1280:720:force_original_aspect_ratio=decrease,"
    "pad=1280:720:(ow-iw)/2:(oh-ih)/2"
)


class VideoError(RuntimeError):
    pass


class VideoRejected(VideoError):
    """str() is safe to show the user."""


def ffmpeg_bin() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise VideoRejected("ffmpeg не установлен")
    return exe


def ffprobe_bin() -> str:
    exe = shutil.which("ffprobe")
    if not exe:
        raise VideoRejected("ffprobe не установлен")
    return exe


def probe(path: Path) -> dict:
    cmd = [
        ffprobe_bin(),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise VideoError(proc.stderr[-400:] or "ffprobe failed")
    return json.loads(proc.stdout or "{}")


def duration_seconds(path: Path) -> float:
    info = probe(path)
    fmt = info.get("format") or {}
    raw = fmt.get("duration")
    try:
        dur = float(raw)
    except (TypeError, ValueError):
        raise VideoRejected("нет длительности")
    if dur <= 0:
        raise VideoRejected("нет длительности")
    return dur


def video_size(path: Path) -> tuple[int, int]:
    info = probe(path)
    for s in info.get("streams") or []:
        if s.get("codec_type") == "video":
            w, h = int(s.get("width") or 0), int(s.get("height") or 0)
            if w and h:
                return w, h
    raise VideoRejected("нет видео-потока")


def _run_ffmpeg(args: list[str]) -> None:
    cmd = [ffmpeg_bin(), "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise VideoError((proc.stderr or proc.stdout or "ffmpeg failed")[-600:])


def _overlay_png(
    video: Path,
    mark: Path,
    dest_png: Path,
    overlay: Overlay,
) -> None:
    from app.engine.image import render_overlay

    w, h = video_size(video)
    dest_png.parent.mkdir(parents=True, exist_ok=True)
    render_overlay((w, h), mark, overlay).save(dest_png, "PNG")


def watermark_video_sync(
    video: Path,
    mark: Path,
    dest: Path,
    *,
    overlay: Overlay,
    max_seconds: int = MAX_VIDEO_SECONDS,
    normalize: bool = False,
) -> Path:
    dur = duration_seconds(video)
    if dur > max_seconds:
        raise VideoRejected(f"видео длиннее {max_seconds} с")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        png = Path(td) / "wm.png"
        _overlay_png(video, mark, png, overlay)
        args = [
            "-i",
            str(video),
            "-i",
            str(png),
            "-filter_complex",
            "overlay=0:0" + ("," + _NORMALIZE_FILTER if normalize else ""),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
        ]
        if normalize:
            args.extend(["-ar", "44100", "-ac", "2", "-r", "30"])
        _run_ffmpeg(
            [
                *args,
                "-movflags",
                "+faststart",
                str(dest),
            ]
        )
    return dest


def concat_sync(first: Path, second: Path, dest: Path, *, normalized: Path | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        a = Path(td) / "a.mp4"
        b = Path(td) / "b.mp4"
        for src, out in ((first, a), (second, b)):
            if src == normalized:
                out.symlink_to(src.resolve())
                continue
            _run_ffmpeg(
                [
                    "-i",
                    str(src),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "23",
                    "-c:a",
                    "aac",
                    "-ar",
                    "44100",
                    "-ac",
                    "2",
                    "-r",
                    "30",
                    "-vf",
                    _NORMALIZE_FILTER,
                    str(out),
                ]
            )
        lst = Path(td) / "list.txt"
        lst.write_text(f"file '{a}'\nfile '{b}'\n", encoding="utf-8")
        _run_ffmpeg(
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(lst),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(dest),
            ]
        )
    return dest


async def exclusive(fn, /, *args, **kwargs):
    async with _sem:
        return await asyncio.to_thread(fn, *args, **kwargs)
