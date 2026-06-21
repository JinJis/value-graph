"""Admin console presentation: the shared chrome (sidebar + topbar), the design
system, and small HTML helpers. Route logic in main.py builds page bodies and wraps
them with ``page(active, title, body)``.

Bodies are composed in Python (escaped via ``_esc``/``_cell``) — there is no untrusted
templating, so the only loaded files are the static ``style`` (literal CSS braces) and
the standalone ``login`` page.
"""

from __future__ import annotations

import html
from pathlib import Path

_TPL_DIR = Path(__file__).parent / "templates"


def _load(name: str) -> str:
    return (_TPL_DIR / f"{name}.html").read_text(encoding="utf-8")


STYLE = _load("style")        # <style>…</style>
_LOGIN = _load("login")       # standalone login page (its own minimal style)

# left-nav information architecture (operator job-to-be-done order)
NAV = [
    ("/", "Overview", "▦"),
    ("/catalog", "Catalog", "◈"),
    ("/pipelines", "Pipelines", "⏣"),
    ("/data", "Data", "▤"),
    ("/users", "Users", "⚇"),
    ("/db", "DB browser", "🗄"),
]


def _esc(v) -> str:
    return html.escape(str(v))


def _cell(v, limit: int = 0) -> str:
    if v is None:
        return "<span class=faint>NULL</span>"
    s = str(v)
    if limit and len(s) > limit:
        s = s[:limit] + "…"
    return _esc(s)


def badge(text: str, kind: str = "") -> str:
    return f"<span class='badge {kind}'>{_esc(text)}</span>"


def sdot(kind: str = "") -> str:
    return f"<span class='sdot {kind}'></span>"


def progress(done, total, kind: str = "") -> str:
    try:
        pct = max(0, min(100, round((done or 0) / total * 100))) if total else 0
    except (TypeError, ZeroDivisionError):
        pct = 0
    return f"<div class='prog {kind}'><i style='width:{pct}%'></i></div>"


def login_page(err: str = "") -> str:
    return _LOGIN.replace("{err}", err)


def page(active: str, title: str, body: str, refresh: bool = False) -> str:
    """Wrap a page body in the console chrome (sidebar nav + topbar)."""
    nav = "".join(
        f"<a class='nav {'on' if href == active else ''}' href='{href}'>"
        f"<span class=i>{ic}</span>{_esc(label)}</a>"
        for href, label, ic in NAV
    )
    meta = "<meta http-equiv=refresh content=5>" if refresh else ""
    return (
        "<!doctype html><html><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>VG Admin · {_esc(title)}</title>{meta}{STYLE}</head><body>"
        "<div class=app>"
        "<aside class=side>"
        "<div class=brand><span class=dot></span>VALUE·GRAPH</div>"
        f"{nav}"
        "<div class=sp></div>"
        "<div class=foot>admin · ops console<br>out-of-band · not in request path</div>"
        "</aside>"
        "<main class=content>"
        f"<header class=bar><h1>{_esc(title)}</h1><a href=/logout>logout ↩</a></header>"
        f"<div class=page>{body}</div>"
        "</main></div></body></html>"
    )
