from pathlib import Path

import pytest

from app.engine.apply import apply_video
from app.engine.video import VideoError, duration_seconds
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
    calls: list[tuple[str, str]] = []

    def fake_wm(_video, _mark, marked, **_kw):
        Path(marked).write_bytes(b"wm")
        return marked

    def fake_concat(first, second, out):
        calls.append((Path(first).name, Path(second).name))
        Path(out).write_bytes(b"out")
        return out

    monkeypatch.setattr(ap, "watermark_video_sync", fake_wm)
    monkeypatch.setattr(ap, "duration_seconds", lambda _p: 1.0)
    monkeypatch.setattr(ap, "concat_sync", fake_concat)

    tpl = Template(id=1, user_id=1, name="t", file_path=str(tmp_path / "m.png"))
    tail = Tail(id=2, user_id=1, name="h", file_path=str(tail_path), placement="end")
    apply_video(video, tpl, dest, tail=tail)
    assert calls == [(dest.stem + "-wm.mp4", tail_path.name)]


def test_apply_video_start_concats_tail_then_marked(tmp_path: Path, monkeypatch):
    from app.engine import apply as ap

    video = tmp_path / "in.mp4"
    video.write_bytes(b"in")
    dest = tmp_path / "out.mp4"
    tail_path = tmp_path / "tail.mp4"
    tail_path.write_bytes(b"tail")
    calls: list[tuple[str, str]] = []

    def fake_wm(_video, _mark, marked, **_kw):
        Path(marked).write_bytes(b"wm")
        return marked

    def fake_concat(first, second, out):
        calls.append((Path(first).name, Path(second).name))
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
