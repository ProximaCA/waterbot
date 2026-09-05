"""Watermark bytes and send. Used from DM and channels."""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import asyncpg

from app.api import max_api
from app.database.repos import jobs as jobs_repo
from app.database.repos import tails as tails_repo
from app.database.repos import templates as tpl_repo
from app.engine.apply import apply_photo, apply_video, tmp_path
from app.engine.image import sniff_image
from app.engine.video import VideoRejected, exclusive
from app.models import Tail, Template, User

MediaKind = Literal["photo", "video"]


async def resolve_template(
    pool: asyncpg.Pool, user_pk: int, template_id: Optional[int]
) -> Optional[Template]:
    if template_id is not None:
        return await tpl_repo.get(pool, template_id, user_pk)
    return await tpl_repo.get_default(pool, user_pk)


async def resolve_tail(pool: asyncpg.Pool, user_pk: int) -> Optional[Tail]:
    if not await tails_repo.tails_enabled(pool, user_pk):
        return None
    return await tails_repo.get_default(pool, user_pk)


async def fetch_image(payload: dict) -> Optional[bytes]:
    blob = await max_api.download_payload(payload)
    if not blob or sniff_image(blob) is None:
        return None
    return blob


def video_user_text(exc: BaseException) -> str:
    if isinstance(exc, VideoRejected):
        return f"Не получилось обработать видео: {exc}"
    return "Не получилось обработать видео."


def _fail_text(kind: MediaKind, exc: BaseException | None) -> str:
    if kind == "photo":
        return "Не получилось обработать фото."
    return video_user_text(exc) if exc else "Не получилось обработать видео."


async def _send_result(
    dest: Path,
    kind: MediaKind,
    user: User,
    chat_id: Optional[int],
) -> Optional[dict]:
    media = "image" if kind == "photo" else "video"
    return await max_api.send_file(
        str(dest),
        kind=media,
        caption="Готово" if chat_id is None else "",
        user_id=None if chat_id is not None else user.max_user_id,
        chat_id=chat_id,
    )


async def _record(
    pool: asyncpg.Pool, user_id: int, kind: MediaKind, *, bytes_out: int, status: str
) -> None:
    try:
        await jobs_repo.record(pool, user_id, kind, bytes_out=bytes_out, status=status)
    except Exception as exc:
        print("jobs.record failed:", repr(exc))


async def process_media(
    pool: asyncpg.Pool,
    user: User,
    data: bytes,
    *,
    kind: MediaKind,
    template: Template,
    tail: Optional[Tail] = None,
    chat_id: Optional[int] = None,
) -> Optional[dict]:
    dest = tmp_path(user.id, ".jpg" if kind == "photo" else ".mp4")
    src: Optional[Path] = None
    r: Optional[dict] = None
    n = 0
    err: BaseException | None = None
    try:
        if kind == "photo":
            apply_photo(data, template, dest)
        else:
            src = tmp_path(user.id, "-in.mp4")
            src.write_bytes(data)
            await exclusive(apply_video, src, template, dest, tail=tail)
        r = await _send_result(dest, kind, user, chat_id)
        n = dest.stat().st_size if dest.exists() else 0
    except Exception as exc:
        print("process_media failed:", repr(exc))
        err = exc
        r = None
        n = 0
    finally:
        dest.unlink(missing_ok=True)
        if src is not None:
            src.unlink(missing_ok=True)
    await _record(pool, user.id, kind, bytes_out=n, status="ok" if r else "fail")
    if r is None and chat_id is None:
        await max_api.send_to_user(user.max_user_id, _fail_text(kind, err))
    return r
