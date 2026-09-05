"""Process-local runtime state."""
from __future__ import annotations

from typing import Optional

BOT_USERNAME: str = ""
BOT_USER_ID: Optional[int] = None

# max_user_id → (kind, expires)
WAIT: dict[int, tuple[str, float]] = {}
