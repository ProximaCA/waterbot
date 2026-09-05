from __future__ import annotations

import asyncio
import json
from typing import Optional

from app.api import max_api
from app.config import POLLING_LIMIT, POLLING_TIMEOUT, POLLING_TYPES
from app.database.connection import get_pool
from app.handlers.dispatch import dispatch


async def poll_updates_loop() -> None:
    marker: Optional[int] = None
    print(
        "POLLING: started",
        f"(timeout={POLLING_TIMEOUT}, limit={POLLING_LIMIT})",
    )
    await asyncio.sleep(1.0)
    while True:
        try:
            st, text = await max_api.get_updates(
                limit=POLLING_LIMIT,
                timeout=POLLING_TIMEOUT,
                marker=marker,
                types=POLLING_TYPES,
            )
            if st != 200:
                print("POLLING /updates failed:", st, text[:300])
                await asyncio.sleep(3)
                continue
            data = json.loads(text)
            marker_value = data.get("marker")
            if isinstance(marker_value, int):
                marker = marker_value
            pool = get_pool()
            for update in data.get("updates") or []:
                try:
                    await dispatch(pool, update)
                except Exception as exc:
                    print("POLLING dispatch failed:", repr(exc))
        except asyncio.CancelledError:
            print("POLLING: stopped")
            raise
        except Exception as exc:
            print("POLLING ERROR:", repr(exc))
            await asyncio.sleep(2)
