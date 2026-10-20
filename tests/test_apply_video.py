import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from app.engine.apply import apply_video
from app.engine.video import VideoError, VideoRejected, duration_seconds, probe
from app.models import Tail, Template


def test_duration_seconds_rejects_non_video(tmp_path: Path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"not a video")
    with pytest.raises(VideoError):
        duration_seconds(p)


def test_apply_video_end_concats_marked_then_tail(tmp_path: Path, monkeypatch):
    from app.engine import apply as ap

    video = tmp_path / "in.mp4"
    video.write_bytes(b"in")
    dest = tmp_path / "out.mp4"
    tail_path = tmp_path / "tail.mp4"
    tail_path.write_bytes(b"tail")
    calls: list[tuple[str, str, str]] = []
    wm_options = []

    def fake_wm(_video, _mark, marked, **kw):
        wm_options.append(kw)
        Path(marked).write_bytes(b"wm")
        return marked

    def fake_concat(first, second, out, *, normalized):
        calls.append((Path(first).name, Path(second).name, Path(normalized).name))
        Path(out).write_bytes(b"out")
        return out

    monkeypatch.setattr(ap, "watermark_video_sync", fake_wm)
    monkeypatch.setattr(ap, "duration_seconds", lambda _p: 1.0)
    monkeypatch.setattr(ap, "concat_sync", fake_concat)

    tpl = Template(id=1, user_id=1, name="t", file_path=str(tmp_path / "m.png"))
    tail = Tail(id=2, user_id=1, name="h", file_path=str(tail_path), placement="end")
    apply_video(video, tpl, dest, tail=tail)
    assert calls == [(dest.stem + "-wm.mp4", tail_path.name, dest.stem + "-wm.mp4")]
    assert wm_options[0]["normalize"] is True


def test_apply_video_start_concats_tail_then_marked(tmp_path: Path, monkeypatch):
    from app.engine import apply as ap

    video = tmp_path / "in.mp4"
    video.write_bytes(b"in")
    dest = tmp_path / "out.mp4"
    tail_path = tmp_path / "tail.mp4"
    tail_path.write_bytes(b"tail")
    calls: list[tuple[str, str, str]] = []
    wm_options = []

    def fake_wm(_video, _mark, marked, **kw):
        wm_options.append(kw)
        Path(marked).write_bytes(b"wm")
        return marked

    def fake_concat(first, second, out, *, normalized):
        calls.append((Path(first).name, Path(second).name, Path(normalized).name))
        Path(out).write_bytes(b"out")
        return out

    monkeypatch.setattr(ap, "watermark_video_sync", fake_wm)
    monkeypatch.setattr(ap, "duration_seconds", lambda _p: 1.0)
    monkeypatch.setattr(ap, "concat_sync", fake_concat)

    tpl = Template(id=1, user_id=1, name="t", file_path=str(tmp_path / "m.png"))
    tail = Tail(id=2, user_id=1, name="h", file_path=str(tail_path), placement="start")
    apply_video(video, tpl, dest, tail=tail)
    assert calls[0][0] == tail_path.name
    assert calls[0][1] == dest.stem + "-wm.mp4"
    assert calls[0][2] == dest.stem + "-wm.mp4"
    assert wm_options[0]["normalize"] is True


def test_apply_video_without_tail_keeps_original_encoding(tmp_path: Path, monkeypatch):
    from app.engine import apply as ap

    options = []

    def fake_wm(_video, _mark, marked, **kw):
        options.append(kw)
        Path(marked).write_bytes(b"wm")

    monkeypatch.setattr(ap, "watermark_video_sync", fake_wm)
    tpl = Template(id=1, user_id=1, name="t", file_path=str(tmp_path / "m.png"))
    dest = tmp_path / "out.mp4"
    apply_video(tmp_path / "in.mp4", tpl, dest)
    assert dest.read_bytes() == b"wm"
    assert options[0]["normalize"] is False


def test_apply_video_rejects_long_tail(tmp_path: Path, monkeypatch):
    from app.engine import apply as ap

    def fake_wm(_video, _mark, marked, **_kw):
        Path(marked).write_bytes(b"wm")

    monkeypatch.setattr(ap, "watermark_video_sync", fake_wm)
    monkeypatch.setattr(ap, "duration_seconds", lambda _path: ap.MAX_TAIL_SECONDS + 1)
    tpl = Template(id=1, user_id=1, name="t", file_path=str(tmp_path / "m.png"))
    tail = Tail(id=2, user_id=1, name="h", file_path=str(tmp_path / "tail.mp4"))
    dest = tmp_path / "out.mp4"
    with pytest.raises(VideoRejected, match=f"хвост длиннее {ap.MAX_TAIL_SECONDS} с"):
        apply_video(tmp_path / "in.mp4", tpl, dest, tail=tail)
    assert not dest.exists()
    assert not (tmp_path / "out-wm.mp4").exists()


def _clip(path: Path, color: str, size: str, *, audio: bool = True) -> None:
    args = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:s={size}:d=0.6"]
    if audio:
        args.extend(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-shortest"])
    args.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p"])
    if audio:
        args.extend(["-c:a", "aac"])
    args.append(str(path))
    subprocess.run(args, check=True, capture_output=True)


def _center_color(path: Path, seconds: float) -> bytes:
    return subprocess.run(
        [
            "ffmpeg", "-v", "error", "-ss", str(seconds), "-i", str(path),
            "-frames:v", "1", "-vf", "crop=8:8:636:356,scale=1:1,format=rgb24",
            "-f", "rawvideo", "pipe:1",
        ],
        check=True,
        capture_output=True,
    ).stdout


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg/ffprobe missing")
@pytest.mark.parametrize("size", ["320x180", "180x320"])
@pytest.mark.parametrize("placement", ["start", "end"])
def test_apply_video_with_tail_ffmpeg(tmp_path: Path, size: str, placement: str):
    src, tail_path, mark, dest = (tmp_path / name for name in ("in.mp4", "tail.mp4", "mark.png", "out.mp4"))
    _clip(src, "red", size)
    _clip(tail_path, "blue", "320x180")
    Image.new("RGBA", (24, 12), (255, 255, 255, 160)).save(mark)
    tpl = Template(id=1, user_id=1, name="t", file_path=str(mark))
    tail = Tail(id=2, user_id=1, name="h", file_path=str(tail_path), placement=placement)

    apply_video(src, tpl, dest, tail=tail)

    streams = probe(dest)["streams"]
    video = next(s for s in streams if s["codec_type"] == "video")
    audio = next(s for s in streams if s["codec_type"] == "audio")
    assert (video["width"], video["height"], video["r_frame_rate"]) == (1280, 720, "30/1")
    assert (audio["codec_name"], audio["sample_rate"], audio["channels"]) == ("aac", "44100", 2)
    first, second = _center_color(dest, 0.1), _center_color(dest, 0.8)
    assert len(first) == len(second) == 3
    assert (first[0] > first[2]) == (placement == "end")
    assert (second[0] > second[2]) == (placement == "start")


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg/ffprobe missing")
@pytest.mark.parametrize("placement,has_audio", [("start", True), ("end", False)])
def test_apply_video_silent_source_keeps_audio_behavior(tmp_path: Path, placement: str, has_audio: bool):
    src, tail_path, mark, dest = (tmp_path / name for name in ("in.mp4", "tail.mp4", "mark.png", "out.mp4"))
    _clip(src, "red", "180x320", audio=False)
    _clip(tail_path, "blue", "320x180")
    Image.new("RGBA", (24, 12), (255, 255, 255, 160)).save(mark)
    tpl = Template(id=1, user_id=1, name="t", file_path=str(mark))
    tail = Tail(id=2, user_id=1, name="h", file_path=str(tail_path), placement=placement)
    apply_video(src, tpl, dest, tail=tail)
    assert any(s["codec_type"] == "audio" for s in probe(dest)["streams"]) is has_audio
