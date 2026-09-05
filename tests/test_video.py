import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from app.engine.video import concat_sync, duration_seconds, watermark_video_sync
from app.models import Overlay

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg/ffprobe missing",
)


def _clip(path: Path, color: str, seconds: str = "0.4") -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=320x240:d={seconds}",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=stereo",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ],
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


def test_concat_sync(tmp_path: Path):
    a, b, dest = tmp_path / "a.mp4", tmp_path / "b.mp4", tmp_path / "c.mp4"
    _clip(a, "red")
    _clip(b, "blue")
    concat_sync(a, b, dest)
    assert dest.exists() and dest.stat().st_size > 1000
    assert duration_seconds(dest) > 0.5
