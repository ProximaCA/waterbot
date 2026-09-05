"""WAIT_* input states with a short TTL."""
from __future__ import annotations

import time
from typing import Optional

from app import state

TTL = 15 * 60

WAIT_WM_IMAGE = "WAIT_WM_IMAGE"
WAIT_TAIL_VIDEO = "WAIT_TAIL_VIDEO"
WAIT_CHANNEL_FORWARD = "WAIT_CHANNEL_FORWARD"


def set_wait(max_user_id: int, kind: str) -> None:
    state.WAIT[max_user_id] = (kind, time.time() + TTL)


def get_wait(max_user_id: int) -> Optional[str]:
    rec = state.WAIT.get(max_user_id)
    if not rec:
        return None
    kind, expires = rec
    if expires < time.time():
        state.WAIT.pop(max_user_id, None)
        return None
    return kind


def clear_wait(max_user_id: int) -> None:
    state.WAIT.pop(max_user_id, None)
