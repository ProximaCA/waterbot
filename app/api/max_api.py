"""MAX Bot API helpers used by the watermark bot."""
from __future__ import annotations

import asyncio
import io
import json
import logging
import mimetypes
import os
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import aiohttp

from app.api.client import _delete, _get, _get_bytes, _patch, _post, _put
from app.config import API_URL, TOKEN, WEBHOOK_UPDATE_TYPES

log = logging.getLogger(__name__)

DEFAULT_BOT_COMMANDS: List[Dict[str, str]] = [
    {"name": "start", "description": "Главное меню"},
]


def _auth_headers() -> Dict[str, str]:
    return {"Authorization": TOKEN}


def _json_headers() -> Dict[str, str]:
    return {**_auth_headers(), "Content-Type": "application/json"}


def disable_link_preview(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload["disable_link_preview"] = True
    return payload


def _proto_code(resp: str) -> str:
    try:
        return str((json.loads(resp) or {}).get("code") or "")
    except Exception:
        return ""


def mid_from_send(resp: Optional[dict]) -> Optional[str]:
    if not isinstance(resp, dict):
        return None
    msg = resp.get("message") or {}
    body = msg.get("body") or {}
    mid = body.get("mid") or msg.get("mid")
    return str(mid) if mid else None


def _json_obj(resp: str) -> Optional[dict]:
    try:
        data = json.loads(resp)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _http_ok(st: int, data: Optional[dict]) -> bool:
    if st == 404:
        return True
    if st != 200 or not data:
        return False
    return data.get("success") is not False


async def get_me() -> Optional[dict]:
    st, text = await _get(f"{API_URL}/me", headers=_auth_headers(), timeout=15)
    if st != 200:
        print("GET /me failed:", st, text[:300])
        return None
    try:
        data = json.loads(text)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    nested = data.get("user") or data.get("bot") or data.get("bot_info")
    if isinstance(nested, dict) and "username" in nested and "username" not in data:
        return nested
    return data


async def set_my_commands(commands: Optional[List[Dict[str, str]]] = None) -> bool:
    raw = commands if commands is not None else DEFAULT_BOT_COMMANDS
    norm: List[Dict[str, str]] = []
    for cmd in raw:
        name = str((cmd or {}).get("name") or "").strip().lstrip("/")
        desc = str((cmd or {}).get("description") or "").strip()
        if name:
            norm.append({"name": name, "description": desc})
    st, text = await _patch_me({"commands": norm})
    if st != 200:
        print("set_my_commands failed:", st, text[:300])
        return False
    return True


async def _patch_me(body: dict) -> tuple[int, str]:
    return await _patch(
        f"{API_URL}/me/commands",
        headers=_json_headers(),
        json_body=body,
        timeout=15,
    )


async def subscribe_bot_webhook(*, url: str, update_types: Optional[List[str]] = None) -> bool:
    types = update_types or [t.strip() for t in WEBHOOK_UPDATE_TYPES.split(",") if t.strip()]
    payload: Dict[str, Any] = {"url": url, "update_types": types}
    st, text = await _post(
        f"{API_URL}/subscriptions",
        headers=_json_headers(),
        json_body=payload,
        timeout=15,
    )
    if st != 200:
        print(f"subscribe_bot_webhook failed: {st} {text[:300]}")
        return False
    return True


async def _post_messages(*, params: dict, json_body: dict, timeout: int) -> tuple[int, str]:
    last_st, last_resp = 0, ""
    for wait in (0, 2, 2, 4):
        if wait:
            await asyncio.sleep(wait)
        st, resp = await _post(
            f"{API_URL}/messages",
            headers=_json_headers(),
            params=params,
            json_body=json_body,
            timeout=timeout,
        )
        last_st, last_resp = st, resp
        if st == 200 or _proto_code(resp) != "attachment.not.ready":
            return st, resp
    return last_st, last_resp


async def send_message(
    *,
    user_id: Optional[int] = None,
    chat_id: Optional[int] = None,
    text: Optional[str] = None,
    keyboard: Optional[List] = None,
    attachments: Optional[List] = None,
    timeout: int = 30,
) -> Optional[dict]:
    if user_id is None and chat_id is None:
        raise ValueError("send_message requires user_id or chat_id")
    params: dict = {"user_id": user_id} if user_id is not None else {"chat_id": chat_id}
    payload = disable_link_preview({})
    if text:
        payload["text"] = text
        payload["format"] = "markdown"
    combined = list(attachments or [])
    if keyboard is not None:
        combined.append({"type": "inline_keyboard", "payload": {"buttons": keyboard}})
    if combined:
        payload["attachments"] = combined
    st, resp = await _post_messages(params=params, json_body=payload, timeout=timeout)
    print("SEND:", st, resp[:400])
    data = _json_obj(resp)
    if st != 200 or not data or data.get("success") is False:
        return None
    return data


async def send_to_user(
    user_id: int,
    text: Optional[str] = None,
    keyboard: Optional[List] = None,
) -> Optional[dict]:
    return await send_message(user_id=user_id, text=text, keyboard=keyboard)


async def edit_message(message_id: str, text: str, keyboard: Optional[List] = None) -> None:
    payload = disable_link_preview({"text": text, "format": "markdown"})
    if keyboard is not None:
        payload["attachments"] = [
            {"type": "inline_keyboard", "payload": {"buttons": keyboard}}
        ]
    st, resp = await _put(
        f"{API_URL}/messages",
        headers=_auth_headers(),
        params={"message_id": message_id},
        json_body=payload,
        timeout=15,
    )
    print("EDIT:", st, resp[:300])
    if st != 200:
        raise RuntimeError(f"edit_message failed ({st}): {resp[:300]}")


async def delete_message(message_id: str) -> bool:
    try:
        st, resp = await _delete(
            f"{API_URL}/messages",
            headers=_auth_headers(),
            params={"message_id": message_id},
            timeout=15,
        )
    except Exception as exc:
        print("DELETED:", repr(exc))
        return False
    print("DELETED:", st, resp[:300])
    return _http_ok(st, _json_obj(resp))


async def answer_callback(
    callback_id: str,
    notification: Optional[str] = None,
) -> None:
    body: Dict[str, Any] = {"notification": notification if notification is not None else ""}
    st, resp = await _post(
        f"{API_URL}/answers",
        headers=_json_headers(),
        params={"callback_id": callback_id},
        json_body=body,
        timeout=10,
    )
    if st != 200:
        print("ANSWER_CB:", st, resp[:200])


async def get_upload_endpoint(file_type: str) -> dict:
    st, resp = await _post(
        f"{API_URL}/uploads",
        headers=_auth_headers(),
        params={"type": file_type},
        timeout=30,
    )
    if st != 200:
        raise RuntimeError(f"get_upload_endpoint failed ({st}): {resp}")
    return json.loads(resp)


async def upload_memory_get_payload(
    *, file_type: str, data: bytes, filename: str, endpoint: Optional[dict] = None,
) -> dict:
    endpoint = endpoint if endpoint is not None else await get_upload_endpoint(file_type)
    upload_url = endpoint["url"]
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    form = aiohttp.FormData()
    form.add_field(
        "data",
        io.BytesIO(data),
        filename=filename or "file.bin",
        content_type=content_type,
    )
    st, resp = await _post(upload_url, data=form, timeout=120)
    if st != 200:
        raise RuntimeError(f"upload failed ({st}): {resp[:600]}")
    body = (resp or "").strip()
    if body:
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            pass
    token = endpoint.get("token")
    if token:
        return {"token": token}
    raise RuntimeError(f"upload: no payload type={file_type} http={st}")


def _read_file(file_path: str) -> bytes:
    with open(file_path, "rb") as f:
        return f.read()


async def send_file(
    file_path: str,
    *,
    kind: str,
    caption: str = "",
    keyboard: Optional[List] = None,
    user_id: Optional[int] = None,
    chat_id: Optional[int] = None,
) -> Optional[dict]:
    data = _read_file(file_path)
    payload = await upload_memory_get_payload(
        file_type=kind, data=data, filename=os.path.basename(file_path),
    )
    return await send_message(
        user_id=user_id,
        chat_id=chat_id,
        text=caption or None,
        keyboard=keyboard,
        attachments=[{"type": kind, "payload": payload}],
        timeout=60,
    )


async def get_updates(
    *, limit: int, timeout: int, marker: Optional[int], types: str
) -> tuple[int, str]:
    params: Dict[str, Any] = {"limit": limit, "timeout": timeout}
    if marker is not None:
        params["marker"] = marker
    if types:
        params["types"] = types
    return await _get(
        f"{API_URL}/updates",
        headers=_auth_headers(),
        params=params,
        timeout=timeout + 15,
    )


def chat_title(info: Optional[dict]) -> str:
    if not isinstance(info, dict):
        return ""
    title = str(info.get("title") or info.get("name") or "")
    nested = info.get("chat") if isinstance(info.get("chat"), dict) else {}
    return title or str(nested.get("title") or "")


def _is_safe_cdn(url: str) -> bool:
    u = (url or "").strip()
    if not u.startswith("https://"):
        return False
    try:
        host = (urlparse(u).hostname or "").lower()
    except ValueError:
        return False
    if not host or host in ("localhost", "127.0.0.1", "::1"):
        return False
    return bool(
        host.endswith(".oneme.ru")
        or host.endswith(".mycdn.me")
        or host.endswith(".okcdn.ru")
        or host.endswith(".max.ru")
        or host == "max.ru"
    )


async def try_download_upload_token(upload_token: str) -> Optional[bytes]:
    tok = str(upload_token or "").strip()
    if not tok:
        return None
    base = API_URL.rstrip("/")
    hdrs = _auth_headers()
    for path in (f"{base}/files/{tok}", f"{base}/files"):
        params = None if path.endswith(f"/{tok}") else {"token": tok}
        try:
            status, blob = await _get_bytes(path, headers=hdrs, params=params)
        except Exception:
            continue
        if status == 200 and blob:
            return bytes(blob)
    return None


async def download_payload(payload: dict) -> Optional[bytes]:
    url = str(payload.get("url") or "").strip()
    if url and _is_safe_cdn(url):
        try:
            status, blob = await _get_bytes(url, timeout=90)
            if status == 200 and blob:
                return bytes(blob)
        except Exception as exc:
            log.debug("cdn get failed: %r", exc)
    tok = str(payload.get("token") or "").strip()
    if tok:
        return await try_download_upload_token(tok)
    return None


async def get_chat(chat_id: int) -> Optional[dict]:
    st, resp = await _get(
        f"{API_URL}/chats/{chat_id}", headers=_auth_headers(), timeout=15
    )
    if st != 200:
        return None
    try:
        return json.loads(resp)
    except Exception:
        return None
