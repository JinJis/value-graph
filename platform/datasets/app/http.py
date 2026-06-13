"""Shared async HTTP client + small fetch helpers used by providers."""

from __future__ import annotations

import httpx

from app.config import settings
from app.errors import upstream_error

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            follow_redirects=True,
            headers={"Accept": "application/json"},
        )
    return _client


async def fetch_json(
    provider: str, url: str, *, params: dict | None = None, headers: dict | None = None
) -> dict | list:
    try:
        resp = await get_client().get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        raise upstream_error(provider, f"HTTP {exc.response.status_code} for {url}")
    except (httpx.HTTPError, ValueError) as exc:
        raise upstream_error(provider, str(exc))


async def fetch_text(
    provider: str, url: str, *, params: dict | None = None, headers: dict | None = None
) -> str:
    try:
        resp = await get_client().get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPStatusError as exc:
        raise upstream_error(provider, f"HTTP {exc.response.status_code} for {url}")
    except httpx.HTTPError as exc:
        raise upstream_error(provider, str(exc))


async def fetch_bytes(
    provider: str, url: str, *, params: dict | None = None, headers: dict | None = None
) -> bytes:
    try:
        resp = await get_client().get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.content
    except httpx.HTTPStatusError as exc:
        raise upstream_error(provider, f"HTTP {exc.response.status_code} for {url}")
    except httpx.HTTPError as exc:
        raise upstream_error(provider, str(exc))
