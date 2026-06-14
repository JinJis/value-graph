"""Shared company-search ranking.

Both the US (SEC) and KR (OpenDART) company providers search their cached
ticker/corp index the same way: match the query against ticker + name and rank
exact/prefix/substring hits. Keeping the ranking here means US and KR return
results ordered consistently.
"""

from __future__ import annotations

from collections.abc import Iterable


def rank_company_matches(query: str, rows: Iterable[dict]) -> list[dict]:
    """Filter+rank ``rows`` (each ``{"ticker", "name", ...}``) against ``query``.

    Best match first: exact ticker, ticker prefix, name prefix, then substring
    in ticker, then substring in name. Non-matches are dropped. Ties break by
    shorter name then alphabetically for stable output.
    """
    q = (query or "").strip().lower()
    if not q:
        return []
    scored: list[tuple] = []
    for row in rows:
        ticker = (row.get("ticker") or "").lower()
        name = (row.get("name") or "").lower()
        if q == ticker:
            score = 0
        elif ticker.startswith(q):
            score = 1
        elif name.startswith(q):
            score = 2
        elif q in ticker:
            score = 3
        elif q in name:
            score = 4
        else:
            continue
        scored.append((score, len(name), name, row))
    scored.sort(key=lambda t: (t[0], t[1], t[2]))
    return [t[3] for t in scored]
