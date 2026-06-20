"""Admin console views: HTML templates (loaded from ./templates/*.html) + cell escaping.

Presentation only — the route logic in main.py composes these. Page bodies render with
str.format (placeholders like ``{msg}``); the shared HEAD/STYLE chrome is concatenated raw
(it contains literal CSS braces and is never formatted).
"""

from __future__ import annotations

import html
from pathlib import Path

_TPL_DIR = Path(__file__).parent / "templates"


def _load(name: str) -> str:
    return (_TPL_DIR / f"{name}.html").read_text(encoding="utf-8")


HEAD = _load("head")    # <!doctype> + meta + title (raw chrome)
STYLE = _load("style")  # <style>…</style> — raw, contains literal CSS braces
_BODIES = {name: _load(name) for name in ("login", "dashboard", "search", "browse", "row")}


def render(name: str, **kw) -> str:
    """Render a page-body template by name, substituting its ``{placeholder}`` tokens."""
    return _BODIES[name].format(**kw)


def _esc(v) -> str:
    return html.escape(str(v))


def _cell(v, limit: int = 0) -> str:
    if v is None:
        return "<span class=muted>NULL</span>"
    s = str(v)
    if limit and len(s) > limit:
        s = s[:limit] + "…"
    return _esc(s)
