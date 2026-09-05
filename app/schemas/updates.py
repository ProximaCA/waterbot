"""Pure extractors from raw MAX update dicts."""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif"}
_VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}


def parse_bot_started(update: dict) -> tuple[Optional[int], Optional[str], Optional[int]]:
    user = update.get("user") or {}
    user_id = user.get("user_id") or update.get("user_id")
    payload = update.get("payload")
    chat_id = update.get("chat_id")
    return user_id, str(payload).strip() if payload else None, chat_id


def parse_message_callback(update: dict) -> tuple[Optional[int], Optional[str], Optional[str]]:
    cb = update.get("callback") or {}
    user = cb.get("user") or {}
    return user.get("user_id"), cb.get("callback_id"), cb.get("payload")


def get_msg(update: dict) -> dict:
    msg = update.get("message") or {}
    return msg if isinstance(msg, dict) else {}


def extract_message_mid(update: dict) -> Optional[str]:
    msg = get_msg(update)
    body = msg.get("body") or {}
    mid = body.get("mid") or msg.get("mid")
    if isinstance(mid, str) and mid:
        return mid
    cb = update.get("callback") or {}
    cmsg = cb.get("message") or {}
    cbody = cmsg.get("body") or {}
    cm = cbody.get("mid") or cmsg.get("mid")
    return str(cm) if cm else None


def extract_sender(update: dict) -> tuple[Optional[int], str]:
    msg = get_msg(update)
    sender = msg.get("sender") or {}
    uid = sender.get("user_id")
    first = (sender.get("first_name") or "").strip()
    last = (sender.get("last_name") or "").strip()
    name = f"{first} {last}".strip() or (sender.get("name") or "").strip() or first
    return uid, name


def extract_text(update: dict) -> str:
    body = (get_msg(update).get("body") or {})
    return (body.get("text") or "").strip()


def extract_recipient(update: dict) -> dict:
    rec = get_msg(update).get("recipient") or {}
    return rec if isinstance(rec, dict) else {}


def extract_chat_id(update: dict) -> Optional[int]:
    rec = extract_recipient(update)
    cid = rec.get("chat_id")
    try:
        return int(cid) if cid is not None else None
    except (TypeError, ValueError):
        return None


def extract_chat_type(update: dict) -> str:
    return str(extract_recipient(update).get("chat_type") or "")


def extract_forward_chat_id(update: dict) -> Optional[int]:
    msg = get_msg(update)
    link = msg.get("link") or {}
    if not isinstance(link, dict) or link.get("type") != "forward":
        return None
    cid = link.get("chat_id")
    if isinstance(cid, int):
        return cid
    fmsg = link.get("message") or {}
    cid2 = fmsg.get("chat_id")
    return cid2 if isinstance(cid2, int) else None


def _body_attachments(part: dict) -> list:
    body = part.get("body") if isinstance(part.get("body"), dict) else part
    atts = body.get("attachments") or []
    return [a for a in atts if isinstance(a, dict)]


def iter_attachments(update: dict) -> list[dict]:
    msg = get_msg(update)
    out: list[dict] = []
    out.extend(_body_attachments(msg))
    link = msg.get("link") or {}
    if isinstance(link, dict) and link.get("type") in {"forward", "reply"}:
        nested = link.get("message") or {}
        if isinstance(nested, dict):
            out.extend(_body_attachments(nested))
    return out


def _image_payload(payload: dict) -> Optional[dict]:
    """One image attachment → one downloadable payload (not a size ladder)."""
    if not isinstance(payload, dict) or not payload:
        return None
    if payload.get("url") or payload.get("token"):
        return payload
    photos = payload.get("photos")
    if isinstance(photos, dict):
        for val in photos.values():
            if isinstance(val, dict) and (val.get("url") or val.get("token")):
                item = dict(val)
                if not item.get("url") and payload.get("url"):
                    item["url"] = payload.get("url")
                return item
            if isinstance(val, str) and val.strip():
                return {"token": val.strip()}
    return None


def _file_suffix(payload: dict) -> str:
    name = str(
        payload.get("filename")
        or payload.get("fileName")
        or payload.get("name")
        or ""
    )
    suffix = Path(name).suffix.lower()
    if suffix:
        return suffix
    url = str(payload.get("url") or "")
    try:
        return Path(urlparse(url).path).suffix.lower()
    except ValueError:
        return ""


def is_round_video(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False
    return bool(
        payload.get("is_round")
        or payload.get("circle")
        or payload.get("video_note")
    )


def extract_media_items(update: dict) -> list[tuple[str, dict]]:
    """Photo/video attachments in order. One payload per image attachment."""
    items: list[tuple[str, dict]] = []
    for att in iter_attachments(update):
        t = str(att.get("type") or "")
        raw = att.get("payload")
        payload = raw if isinstance(raw, dict) else {}
        if t == "video" and payload and not is_round_video(payload):
            items.append(("video", payload))
        elif t == "image":
            picked = _image_payload(payload)
            if picked:
                items.append(("photo", picked))
        elif t == "file" and payload:
            suf = _file_suffix(payload)
            if suf in _VIDEO_EXT:
                items.append(("video", payload))
            elif suf in _IMAGE_EXT or not suf:
                items.append(("photo", payload))
    return items


def payload_stem(payload: dict) -> str:
    raw = str(
        payload.get("filename")
        or payload.get("fileName")
        or payload.get("name")
        or ""
    )
    return Path(raw).stem.strip()[:32]


_UNSUPPORTED = frozenset({"sticker", "audio", "contact", "location", "video_note"})


def extract_unsupported_types(update: dict) -> list[str]:
    out: list[str] = []
    for att in iter_attachments(update):
        t = str(att.get("type") or "")
        payload = att.get("payload") if isinstance(att.get("payload"), dict) else {}
        if t in _UNSUPPORTED:
            out.append(t)
        elif t == "video" and is_round_video(payload):
            out.append("video_note")
    return out



