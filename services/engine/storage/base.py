"""Storage protocol — the minimal surface the engine needs for blobs."""

from __future__ import annotations

from typing import Protocol


class Storage(Protocol):
    def save(self, key: str, data: bytes) -> None: ...

    def load(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...
