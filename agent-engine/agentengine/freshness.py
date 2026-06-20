"""Freshness from an as-of date (PH-4/U2).

Until the Disclosure Calendar lands (U4 — which gives a real next-expected-update),
freshness is computed from age alone: ``fresh`` < 30d · ``aging`` < 90d · ``stale``
otherwise. Returns None when there's no parseable date (unknown, not a claim).
"""

from __future__ import annotations

from datetime import date, datetime

FRESH_DAYS = 30
AGING_DAYS = 90


def _parse(as_of: str | None) -> date | None:
    if not as_of:
        return None
    try:
        return datetime.strptime(str(as_of)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def compute_freshness(as_of: str | None, today: date | None = None) -> str | None:
    d = _parse(as_of)
    if d is None:
        return None
    age = ((today or date.today()) - d).days
    if age < FRESH_DAYS:
        return "fresh"
    if age < AGING_DAYS:
        return "aging"
    return "stale"
