"""[M1-THEME-01] LocalStorage save/load/exists + path-traversal guard."""

from __future__ import annotations

from pathlib import Path

import pytest

from services.engine.storage.local import LocalStorage


def test_save_load_roundtrip(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    storage.save("theme/abc/file.pdf", b"hello bytes")
    assert storage.exists("theme/abc/file.pdf")
    assert storage.load("theme/abc/file.pdf") == b"hello bytes"


def test_missing_key_not_exists(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    assert not storage.exists("nope")


def test_path_traversal_rejected(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    with pytest.raises(ValueError):
        storage.save("../escape.txt", b"x")
