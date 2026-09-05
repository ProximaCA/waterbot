"""Channel auto-watermark: claim mid, process, delete original."""
from __future__ import annotations

import asyncpg

from app.api import max_api
from app.database.repos import channels as ch_repo
from app.database.repos import tails as tails_repo
from app.database.repos import users as user_repo
from app.handlers import pipeline
from app.schemas.updates import (
    extract_chat_id,
    extract_media_items,
    extract_message_mid,
)


async def handle_channel_post(pool: asyncpg.Pool, update: dict) -> None:
    chat_id = extract_chat_id(update)
    mid = extract_message_mid(update)
    if not chat_id or not mid:
        return
    ch = await ch_repo.get_by_chat(pool, chat_id)
    if not ch or not ch.enabled:
        return
    items = extract_media_items(update)
    if not items:
        return
    if not await ch_repo.mark_processed(pool, chat_id, mid):
        return
    sent_ok = 0
    try:
        user = await user_repo.get_by_id(pool, ch.user_id)
        tpl = (
            await pipeline.resolve_template(pool, user.id, ch.template_id)
            if user
            else None
        )
        if not user or not tpl:
            return
        for kind, payload in items:
            blob = (
                await pipeline.fetch_image(payload)
                if kind == "photo"
                else await max_api.download_payload(payload)
            )
            if not blob:
                continue
            tail = None
            if kind == "video" and ch.use_tail:
                tail = await tails_repo.get_default(pool, user.id)
            sent = await pipeline.process_media(
                pool, user, blob, kind=kind, template=tpl, tail=tail, chat_id=chat_id
            )
            if not sent:
                continue
            sent_ok += 1
            out_mid = max_api.mid_from_send(sent)
            if out_mid:
                try:
                    await ch_repo.mark_processed(pool, chat_id, out_mid)
                except Exception as exc:
                    print("mark outgoing failed:", repr(exc))
        if sent_ok == len(items):
            if not await max_api.delete_message(mid):
                print("delete original failed:", mid)
    except Exception as exc:
        print("channel post failed:", repr(exc))
    finally:
        if not sent_ok:
            await ch_repo.unmark_processed(pool, chat_id, mid)
