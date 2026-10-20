"""Edit channel media in place only after all replacements are ready."""
from __future__ import annotations

import asyncio
from weakref import WeakValueDictionary

import asyncpg

from app import state
from app.api import max_api
from app.database.repos import channels as ch_repo
from app.database.repos import tails as tails_repo
from app.database.repos import users as user_repo
from app.engine.apply import apply_photo, apply_video, tmp_path
from app.engine.video import exclusive
from app.handlers import pipeline
from app.schemas.updates import extract_chat_id, extract_media_items, extract_message_mid

# Keep duplicate webhooks for one post serialized, while different posts can run together.
_locks: WeakValueDictionary[tuple[int, str], asyncio.Lock] = WeakValueDictionary()
# Four in-flight attachments across all channel posts bound memory and MAX requests.
_media_sem = asyncio.Semaphore(4)


async def _read_post(chat_id: int, mid: str) -> dict:
    status, response = await max_api._get(
        f"{max_api.API_URL}/messages", headers=max_api._auth_headers(),
        params={"message_ids": mid}, timeout=20,
    )
    data = max_api._json_obj(response) or {}
    if status == 200:
        for message in data.get("messages") or []:
            if (extract_message_mid({"message": message}) == mid
                    and extract_chat_id({"message": message}) == chat_id):
                return message
    raise ValueError("Could not read the original channel post")


def _attachments(message: dict) -> list:
    body = message.get("body") or {}
    link = message.get("link") or {}
    if not body.get("attachments") and link.get("type") == "forward":
        body = (link.get("message") or {}).get("body") or {}
    return body.get("attachments") or []


def _media_identity(attachments: list) -> list:
    # MAX refreshes media tokens on GET; photo_id/id identify the actual media.
    return [(a.get("type"), (a.get("payload") or {}).get("photo_id")
             or (a.get("payload") or {}).get("id") or a.get("payload"))
            for a in attachments if a.get("type") != "inline_keyboard"]


async def _upload_item(user, template, tail, kind, data):
    dest = tmp_path(user.id, ".jpg" if kind == "photo" else ".mp4")
    src = None
    media = "image" if kind == "photo" else "video"
    endpoint_task = asyncio.create_task(max_api.get_upload_endpoint(media))
    try:
        if kind == "photo":
            await asyncio.to_thread(apply_photo, data, template, dest)
        else:
            src = tmp_path(user.id, "-in.mp4")
            await asyncio.to_thread(src.write_bytes, data)
            await exclusive(apply_video, src, template, dest, tail=tail)
        blob = await asyncio.to_thread(dest.read_bytes)
        payload = await max_api.upload_memory_get_payload(
            file_type=media, data=blob, filename=dest.name, endpoint=await endpoint_task,
        )
        return {"type": media, "payload": payload}, len(blob)
    finally:
        endpoint_task.cancel()
        await asyncio.gather(endpoint_task, return_exceptions=True)
        dest.unlink(missing_ok=True)
        if src:
            src.unlink(missing_ok=True)


async def handle_channel_post(pool: asyncpg.Pool, update: dict) -> None:
    chat_id = extract_chat_id(update)
    mid = extract_message_mid(update)
    if not chat_id or not mid:
        return
    lock = _locks.setdefault((chat_id, mid), asyncio.Lock())
    async with lock:
        await _replace_post(pool, update, chat_id, mid)


async def _replace_post(pool, update, chat_id, mid):
    message = update.get("message") or {}
    if state.BOT_USER_ID and (message.get("sender") or {}).get("user_id") == state.BOT_USER_ID:
        return
    ch = await ch_repo.get_by_chat(pool, chat_id)
    if not ch or not ch.enabled:
        return
    if not await ch_repo.mark_processed(pool, chat_id, mid):
        return
    edited = False
    try:
        print("channel received:", chat_id, mid, flush=True)
        source = _attachments(await _read_post(chat_id, mid))
        media = [a for a in source if a.get("type") != "inline_keyboard"]
        items = extract_media_items({"message": {"body": {"attachments": media}}})
        if not items or len(items) != len(media):
            print("channel skipped: unsupported attachments", chat_id, mid,
                  [a.get("type") for a in source], flush=True)
            return
        user = await user_repo.get_by_id(pool, ch.user_id)
        template = await pipeline.resolve_template(pool, user.id, ch.template_id) if user else None
        if not user or not template:
            print("channel skipped: no template", chat_id, mid, flush=True)
            return
        tail = (await tails_repo.get_default(pool, user.id)
                if ch.use_tail and any(kind == "video" for kind, _ in items) else None)
        async def prepare(kind, payload):
            async with _media_sem:
                blob = (await pipeline.fetch_image(payload) if kind == "photo"
                        else await max_api.download_payload(payload))
                if not blob:
                    raise ValueError(f"download {kind}")
                return await _upload_item(
                    user, template, tail if kind == "video" else None, kind, blob)

        # Drain every worker on error: image threads may continue after cancellation.
        results = await asyncio.gather(
            *(prepare(kind, payload) for kind, payload in items),
            return_exceptions=True,
        )
        if any(isinstance(item, BaseException) for item in results):
            print("channel failed: attachment", chat_id, mid,
                  [repr(item) for item in results if isinstance(item, BaseException)],
                  flush=True)
            return
        replacements = [attachment for attachment, _ in results]
        sizes = [(kind, size) for (kind, _), (_, size) in zip(items, results)]
        for wait in (0, 2, 2, 4):
            if wait:
                await asyncio.sleep(wait)
            # A comments bot or the author may have edited this post during rendering.
            current = _attachments(await _read_post(chat_id, mid))
            if _media_identity(current) != _media_identity(media):
                print("channel skipped: media changed", chat_id, mid, flush=True)
                return
            ready = iter(replacements)
            attachments = [a if a.get("type") == "inline_keyboard" else next(ready)
                           for a in current]
            status, response = await max_api._put(
                f"{max_api.API_URL}/messages", headers=max_api._auth_headers(),
                params={"message_id": mid}, json_body={"attachments": attachments}, timeout=60,
            )
            if status == 200 and (max_api._json_obj(response) or {}).get("success") is True:
                edited = True
                break
            if max_api._proto_code(response) != "attachment.not.ready":
                break
        if not edited:
            print("channel failed: edit", chat_id, mid, status,
                  max_api._proto_code(response), flush=True)
            return
        print("channel edited:", chat_id, mid, flush=True)
        for kind, size in sizes:
            await pipeline._record(pool, user.id, kind, bytes_out=size, status="ok")
    except Exception as exc:
        print("channel post failed:", repr(exc))
    finally:
        if not edited:
            await ch_repo.unmark_processed(pool, chat_id, mid)
