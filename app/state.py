"""Process-local runtime state."""
from __future__ import annotations

from typing import Optional

BOT_USERNAME: str = ""
BOT_USER_ID: Optional[int] = None

# max_user_id → (kind, expires)
WAIT: dict[int, tuple[str, float]] = {}

# max_user_id → (template slot, upload prompt message id)
TEMPLATE_UPLOAD: dict[int, tuple[int, Optional[str]]] = {}

# Last screen outside the templates section, used by its Back button.
TEMPLATE_RETURN: dict[int, tuple[str, list[str]]] = {}

# Last interactive screen; processed media and downloaded files are not UI screens.
UI_MID: dict[int, str] = {}
CHANNEL_RETURN: dict[int, str] = {}
