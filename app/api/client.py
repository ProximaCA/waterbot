"""Shared aiohttp session and HTTP verbs."""
from __future__ import annotations

import ssl
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import aiohttp

_session: aiohttp.ClientSession | None = None
_CERTS = Path(__file__).resolve().parent.parent.parent / "deploy" / "certs"


def ssl_context() -> ssl.SSLContext:
    """Trust system/Mozilla CAs plus the bundled Russian Trusted Root (MAX API)."""
    ctx = ssl.create_default_context()
    try:
        import certifi

        ctx.load_verify_locations(cafile=certifi.where())
    except Exception:
        pass
    for name in ("russian_trusted_root_ca.pem", "russian_trusted_sub_ca.pem"):
        path = _CERTS / name
        if path.exists():
            ctx.load_verify_locations(cafile=str(path))
    return ctx


def set_session(session: aiohttp.ClientSession | None) -> None:
    global _session
    _session = session


def get_session() -> aiohttp.ClientSession:
    if _session is None:
        raise RuntimeError("HTTP session has not been initialised yet.")
    return _session


async def _get(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
) -> Tuple[int, str]:
    async with get_session().get(
        url, headers=headers, params=params, timeout=timeout
    ) as r:
        return r.status, await r.text()


async def _get_bytes(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 60,
) -> Tuple[int, bytes]:
    async with get_session().get(
        url, headers=headers, params=params, timeout=timeout
    ) as r:
        return r.status, await r.read()


async def _post(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Any] = None,
    data: Any = None,
    timeout: int = 30,
) -> Tuple[int, str]:
    async with get_session().post(
        url,
        headers=headers,
        params=params,
        json=json_body,
        data=data,
        timeout=timeout,
    ) as r:
        return r.status, await r.text()


async def _put(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Any] = None,
    timeout: int = 30,
) -> Tuple[int, str]:
    async with get_session().put(
        url, headers=headers, params=params, json=json_body, timeout=timeout
    ) as r:
        return r.status, await r.text()


async def _patch(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Any] = None,
    timeout: int = 30,
) -> Tuple[int, str]:
    async with get_session().patch(
        url, headers=headers, params=params, json=json_body, timeout=timeout
    ) as r:
        return r.status, await r.text()


async def _delete(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
) -> Tuple[int, str]:
    async with get_session().delete(
        url, headers=headers, params=params, timeout=timeout
    ) as r:
        return r.status, await r.text()
