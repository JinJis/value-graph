"""In-process registry of editable prompt templates.

Each prompt-building site **registers** its default instruction text once (at import) and then
reads the EFFECTIVE text via :func:`get` — which returns an admin override if one is set, else
the registered default. Overrides are persisted in Postgres (``prompt_overrides``) and loaded
into this process-global cache at startup; the prompts API updates both on edit.

This keeps the default text next to the code that uses it (good locality) while letting the
admin tune any prompt at runtime without a redeploy. Dynamic context (theme, companies, target
count, …) is still assembled in code around ``get(key)`` — only the static guidance is editable.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class PromptSpec:
    """A registered prompt: its stable key, human label, and built-in default text."""

    key: str
    title: str
    description: str
    default: str


_specs: dict[str, PromptSpec] = {}
_overrides: dict[str, str] = {}
_lock = threading.Lock()


def register(key: str, title: str, description: str, default: str) -> str:
    """Register a prompt's default text (idempotent); returns the key for convenience."""
    with _lock:
        _specs[key] = PromptSpec(key=key, title=title, description=description, default=default)
    return key


def get(key: str) -> str:
    """The effective text for ``key`` — the admin override if set, else the default."""
    with _lock:
        if key in _overrides:
            return _overrides[key]
        spec = _specs.get(key)
        return spec.default if spec is not None else ""


def has(key: str) -> bool:
    with _lock:
        return key in _specs


def spec(key: str) -> PromptSpec | None:
    with _lock:
        return _specs.get(key)


def specs() -> list[PromptSpec]:
    """All registered prompts, sorted by key (stable order for the UI)."""
    with _lock:
        return sorted(_specs.values(), key=lambda s: s.key)


def override(key: str) -> str | None:
    with _lock:
        return _overrides.get(key)


def load_overrides(items: dict[str, str]) -> None:
    """Replace the override cache (called at startup from the persisted store)."""
    with _lock:
        _overrides.clear()
        _overrides.update(items)


def apply_override(key: str, text: str) -> None:
    with _lock:
        _overrides[key] = text


def clear_override(key: str) -> None:
    with _lock:
        _overrides.pop(key, None)
