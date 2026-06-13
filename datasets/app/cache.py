"""A tiny async TTL cache.

In-memory by default (sufficient for a single-process dev/staging deployment).
``redis_url`` is reserved for a future shared-cache backend; the interface below
is intentionally backend-agnostic so swapping it in later touches only this file.
"""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, TypeVar

from app.config import settings

T = TypeVar("T")


class TTLCache:
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, object]] = {}
        self._lock = asyncio.Lock()

    async def get_or_set(self, key: str, factory: Callable[[], Awaitable[T]]) -> T:
        now = time.monotonic()
        async with self._lock:
            hit = self._store.get(key)
            if hit is not None and hit[0] > now:
                return hit[1]  # type: ignore[return-value]
        value = await factory()
        async with self._lock:
            self._store[key] = (now + self._ttl, value)
        return value

    def clear(self) -> None:
        self._store.clear()


cache = TTLCache(settings.cache_ttl_seconds)
