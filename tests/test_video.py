import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from app.engine.video import concat_sync, duration_seconds, probe, watermark_video_sync
from app.models import Overlay

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg/ffprobe missing",
)


def _clip(path: Path, color: str, seconds: str = "0.4", *, audio: bool = True) -> None:
    args = [
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=320x240:d={seconds}",
    ]
    if audio:
        args.extend(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-shortest"])
    args.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p"])
    if audio:
        args.extend(["-c:a", "aac"])
    args.append(str(path))
    subprocess.run(
        args,
        check=True,
        capture_output=True,
    )


def test_watermark_video_sync(tmp_path: Path):
    src = tmp_path / "in.mp4"
    mark = tmp_path / "wm.png"
    dest = tmp_path / "out.mp4"
    _clip(src, "green")
    Image.new("RGBA", (48, 24), (255, 0, 0, 200)).save(mark)
    watermark_video_sync(src, mark, dest, overlay=Overlay())
    assert dest.exists() and dest.stat().st_size > 1000
    assert duration_seconds(dest) > 0.2


def test_normalized_watermark_without_audio(tmp_path: Path):
    src, mark, dest = (tmp_path / name for name in ("in.mp4", "wm.png", "out.mp4"))
    _clip(src, "green", audio=False)
    Image.new("RGBA", (48, 24), (255, 0, 0, 200)).save(mark)
    watermark_video_sync(src, mark, dest, overlay=Overlay(), normalize=True)
    streams = probe(dest)["streams"]
    video = next(s for s in streams if s["codec_type"] == "video")
    assert (video["width"], video["height"], video["r_frame_rate"]) == (1280, 720, "30/1")
    assert not any(s["codec_type"] == "audio" for s in streams)


def test_concat_sync(tmp_path: Path):
    a, b, dest = tmp_path / "a.mp4", tmp_path / "b.mp4", tmp_path / "c.mp4"
    _clip(a, "red")
    _clip(b, "blue")
    concat_sync(a, b, dest)
    assert dest.exists() and dest.stat().st_size > 1000
    assert duration_seconds(dest) > 0.5


def test_concat_sync_skips_normalized_video(tmp_path: Path, monkeypatch):
    from app.engine import video as engine

    quoted = tmp_path / "quoted'folder"
    quoted.mkdir()
    src, tail, mark, marked, dest = (quoted / name for name in ("in.mp4", "tail.mp4", "wm.png", "marked.mp4", "out.mp4"))
    _clip(src, "red")
    _clip(tail, "blue")
    Image.new("RGBA", (48, 24), (255, 0, 0, 200)).save(mark)
    watermark_video_sync(src, mark, marked, overlay=Overlay(), normalize=True)

    original = engine._run_ffmpeg
    calls = []

    def record(args):
        calls.append(args)
        original(args)

    monkeypatch.setattr(engine, "_run_ffmpeg", record)
    concat_sync(marked, tail, dest, normalized=marked)
    assert dest.exists()
    assert len(calls) == 2
    assert "libx264" in calls[0]
    assert "libx264" not in calls[1]
