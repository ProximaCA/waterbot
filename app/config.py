"""Env-driven config. ``.env.config`` then ``.env`` (secrets win)."""
from __future__ import annotations

import os
from pathlib import Path


def _load_env_file(path: Path, *, override: bool) -> None:
    if not path.exists():
        return
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if not key:
            continue
        if override:
            os.environ[key] = value
        else:
            os.environ.setdefault(key, value)


def _load_dotenv() -> None:
    root = Path(__file__).resolve().parent.parent
    _load_env_file(root / ".env.config", override=False)
    _load_env_file(root / ".env", override=True)


_load_dotenv()

ROOT = Path(__file__).resolve().parent.parent

API_URL: str = os.getenv("API_URL", "https://platform-api2.max.ru").strip()
TOKEN: str = os.getenv("MAX_TOKEN", "").strip()

USE_WEBHOOK: bool = os.getenv("USE_WEBHOOK", "false").strip().lower() in {"1", "true"}
WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "").strip()
WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "8010"))
WEBHOOK_PATH: str = os.getenv("WEBHOOK_PATH", "/max-webhook").strip()
WEBHOOK_UPDATE_TYPES: str = os.getenv(
    "WEBHOOK_UPDATE_TYPES",
    "bot_started,bot_stopped,message_created,message_callback",
).strip()
POLLING_TIMEOUT: int = int(os.getenv("POLLING_TIMEOUT", "25"))
POLLING_LIMIT: int = int(os.getenv("POLLING_LIMIT", "100"))
POLLING_TYPES: str = os.getenv("POLLING_TYPES", WEBHOOK_UPDATE_TYPES).strip()

DATABASE_URL: str = os.getenv(
    "DATABASE_URL", "postgresql://watermark:watermark@127.0.0.1:5433/watermarkbot"
).strip()

DATA_DIR: Path = Path(os.getenv("DATA_DIR", str(ROOT / "data"))).resolve()

MAX_VIDEO_SECONDS: int = int(os.getenv("MAX_VIDEO_SECONDS", "180"))
MAX_TAIL_SECONDS: int = int(os.getenv("MAX_TAIL_SECONDS", "15"))
FFMPEG_CONCURRENCY: int = int(os.getenv("FFMPEG_CONCURRENCY", "1"))

if not TOKEN:
    print("WARNING: MAX_TOKEN is not set.")
