"""Local-filesystem Storage backend (dev). Keys are stored as paths under a root."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_STORAGE_DIR = ".data/storage"


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        target = (self._root / key).resolve()
        if not target.is_relative_to(self._root):
            raise ValueError(f"invalid storage key (path traversal): {key!r}")
        return target

    def save(self, key: str, data: bytes) -> None:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def load(self, key: str) -> bytes:
        return self._resolve(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()


def local_storage_from_env(env: dict[str, str] | None = None) -> LocalStorage:
    source = os.environ if env is None else env
    return LocalStorage(Path(source.get("STORAGE_DIR", DEFAULT_STORAGE_DIR)))
