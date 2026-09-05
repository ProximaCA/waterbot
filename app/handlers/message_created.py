from __future__ import annotations

import asyncpg

from app.api import max_api
from app.config import MAX_TAIL_SECONDS
from app.database.repos import channels as ch_repo
from app.database.repos import tails as tails_repo
from app.database.repos import templates as tpl_repo
from app.database.repos import users as user_repo
from app.engine.apply import store_upload
from app.engine.image import sniff_image
from app.engine.video import VideoError, duration_seconds
from app.handlers import pipeline
from app.handlers.channel import handle_channel_post
from app.keyboards.builders import no_template_kb
from app.models import User
from app.renderers import views
from app.renderers.views import Screen
from app.schemas.updates import (
    extract_chat_type,
    extract_forward_chat_id,
    extract_media_items,
    extract_sender,
    extract_text,
    extract_unsupported_types,
    payload_stem,
)
from app.wait import (
    WAIT_CHANNEL_FORWARD,
    WAIT_TAIL_VIDEO,
    WAIT_WM_IMAGE,
    clear_wait,
    get_wait,
)


async def handle_message_created(pool: asyncpg.Pool, update: dict) -> None:
    chat_type = extract_chat_type(update)
    if chat_type == "channel":
        await handle_channel_post(pool, update)
        return
    if chat_type and chat_type not in ("dialog", ""):
        print("skip chat_type", chat_type, flush=True)
        return
    sender_id, name = extract_sender(update)
    if not sender_id:
        print("DM skip: no sender", chat_type, flush=True)
        return
    user = await user_repo.upsert_user(pool, int(sender_id), name)
    text = extract_text(update)
    wait = get_wait(int(sender_id))

    if text.startswith("/start"):
        clear_wait(int(sender_id))
        await views.show_templates(pool, user, Screen.for_user(user))
        return

    ingest = {
        WAIT_WM_IMAGE: _ingest_template,
        WAIT_TAIL_VIDEO: _ingest_tail,
        WAIT_CHANNEL_FORWARD: _ingest_channel,
    }.get(wait)
    if ingest:
        await ingest(pool, user, update)
        return

    media = extract_media_items(update)
    if media:
        await _apply_items(pool, user, media)
        return
    if extract_unsupported_types(update):
        await max_api.send_to_user(user.max_user_id, "этот тип не поддерживается")
        return
    if text:
        await views.show_templates(pool, user, Screen.for_user(user))


def _first_media(update: dict, kind: str) -> dict | None:
    return next((p for k, p in extract_media_items(update) if k == kind), None)


async def _ingest_template(pool, user: User, update: dict) -> None:
    payload = _first_media(update, "photo")
    if not payload:
        await max_api.send_to_user(
            user.max_user_id, "Нужна картинка. Пришлите файл или фото."
        )
        return
    blob = await max_api.download_payload(payload)
    if not blob:
        await max_api.send_to_user(
            user.max_user_id, "Не скачал картинку, попробуйте ещё раз."
        )
        return
    suffix = sniff_image(blob)
    if not suffix:
        await max_api.send_to_user(
            user.max_user_id, "Нужна картинка. Пришлите файл или фото."
        )
        return
    path = store_upload(user.id, blob, suffix)
    n = len(await tpl_repo.list_for(pool, user.id))
    name = payload_stem(payload) or f"Шаблон {n + 1}"
    t = await tpl_repo.create(pool, user.id, name=name, file_path=str(path))
    clear_wait(user.max_user_id)
    await views.show_template_card(pool, user, t, Screen.for_user(user))


async def _ingest_tail(pool, user: User, update: dict) -> None:
    payload = _first_media(update, "video")
    if not payload:
        await max_api.send_to_user(user.max_user_id, "Нужно видео. Пришлите ролик.")
        return
    blob = await max_api.download_payload(payload)
    if not blob:
        await max_api.send_to_user(
            user.max_user_id, "Не скачал видео, попробуйте ещё раз."
        )
        return
    path = store_upload(user.id, blob, ".mp4")
    try:
        dur = duration_seconds(path)
    except VideoError as exc:
        path.unlink(missing_ok=True)
        await max_api.send_to_user(user.max_user_id, pipeline.video_user_text(exc))
        return
    if dur > MAX_TAIL_SECONDS:
        path.unlink(missing_ok=True)
        await max_api.send_to_user(
            user.max_user_id, f"Хвост длиннее {MAX_TAIL_SECONDS} секунд."
        )
        return
    n = len(await tails_repo.list_for(pool, user.id))
    t = await tails_repo.create(pool, user.id, name=f"Хвост {n + 1}", file_path=str(path))
    clear_wait(user.max_user_id)
    await views.show_tail_card(pool, user, t, Screen.for_user(user))


async def _ingest_channel(pool, user: User, update: dict) -> None:
    chat_id = extract_forward_chat_id(update)
    if not chat_id:
        await max_api.send_to_user(
            user.max_user_id,
            "Перешлите пост из канала, не копируйте текст.",
        )
        return
    title = max_api.chat_title(await max_api.get_chat(chat_id)) or str(chat_id)
    c = await ch_repo.upsert(pool, user.id, chat_id, title)
    if c is None:
        await max_api.send_to_user(user.max_user_id, "Этот канал уже привязан.")
        return
    clear_wait(user.max_user_id)
    await views.show_channel_card(pool, user, c, Screen.for_user(user))


async def _need_template(user: User) -> None:
    await max_api.send_to_user(
        user.max_user_id,
        "Сначала добавьте водяной знак.",
        keyboard=no_template_kb(),
    )


async def _apply_items(
    pool, user: User, items: list[tuple[str, dict]]
) -> None:
    tpl = await pipeline.resolve_template(pool, user.id, None)
    if not tpl:
        await _need_template(user)
        return
    kinds = {k for k, _ in items}
    if kinds == {"video"}:
        progress = "Обрабатываю видео…"
    else:
        progress = "Обрабатываю…"
    await max_api.send_to_user(user.max_user_id, progress)
    for kind, payload in items:
        if kind == "photo":
            blob = await pipeline.fetch_image(payload)
            miss, tail = "Не скачал фото.", None
        else:
            blob = await max_api.download_payload(payload)
            miss = "Не скачал видео."
            tail = await pipeline.resolve_tail(pool, user.id)
        if not blob:
            await max_api.send_to_user(user.max_user_id, miss)
            continue
        await pipeline.process_media(
            pool, user, blob, kind=kind, template=tpl, tail=tail
        )
