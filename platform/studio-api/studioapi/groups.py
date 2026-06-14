"""@handle resolution (U1-03).

A user types ``@반도체바스켓`` in chat (or an analyst's system prompt references a
group). Before the turn reaches the agent engine we expand each ``@handle`` to the
concrete companies in that user's watchlist, so the planner calls tools for exactly
those tickers. The user's original text (with the bare @handle) is what we persist
and show; only the copy sent to the agent is expanded. Unknown/empty handles get a
graceful inline note instead of silently vanishing.
"""

from __future__ import annotations

import re

from sqlalchemy import select

from studioapi.models import Watchlist, WatchlistItem

# @ followed by ASCII word chars or Hangul (watchlist handles allow Korean names).
_HANDLE_RE = re.compile(r"@([0-9A-Za-z_가-힣]+)")


def expand_text(db, user_email: str, text: str | None) -> str:
    """Replace each ``@handle`` in ``text`` with ``@handle (handle = company list)``."""
    if not text or "@" not in text:
        return text or ""

    def _sub(match: re.Match) -> str:
        handle = match.group(1)
        wl = db.execute(
            select(Watchlist).where(Watchlist.user_email == user_email, Watchlist.name == handle)
        ).scalars().first()
        if wl is None:
            return f"{match.group(0)} (알 수 없는 관심 그룹)"
        items = db.execute(
            select(WatchlistItem).where(WatchlistItem.watchlist_id == wl.id)
            .order_by(WatchlistItem.added_at.asc())
        ).scalars().all()
        if not items:
            return f"{match.group(0)} (빈 그룹)"
        listed = ", ".join(f"{it.name or it.ticker} [{it.ticker}, {it.market}]" for it in items)
        return f"{match.group(0)} ({handle} = {listed})"

    return _HANDLE_RE.sub(_sub, text)


def resolve_messages(db, user_email: str, messages: list[dict]) -> list[dict]:
    """Return a copy of ``messages`` with @handles in user turns expanded."""
    out: list[dict] = []
    for m in messages:
        if m.get("role") == "user" and m.get("content"):
            out.append({**m, "content": expand_text(db, user_email, m["content"])})
        else:
            out.append(m)
    return out
