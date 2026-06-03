"""S6: Scoring — confidence tier + interval + freshness + next_expected_update (PRD §6.2/§6.4).

Confidence tier:
- verified:  primary disclosure corroborated by >=2 independent sources, OR exact math
             from a primary filing.
- derived:   a single disclosure + math.
- estimated: algorithmic only.

Freshness (periodic figures): fresh (<~30d) | aging | stale (past next-expected) | gap.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from services.engine.cve.reconcile import Interval

FRESH_DAYS = 30


def confidence_tier(
    *, n_independent_sources: int, estimated: bool, exact_from_primary: bool = False
) -> str:
    if estimated:
        return "estimated"
    if n_independent_sources >= 2 or exact_from_primary:
        return "verified"
    if n_independent_sources >= 1:
        return "derived"
    return "estimated"  # 0 sources -> algorithmic only


def freshness(
    *, as_of: date | None, next_expected_update: date | None, today: date
) -> str:
    if as_of is None:
        return "gap"
    if next_expected_update is not None and today > next_expected_update:
        return "stale"
    if (today - as_of).days <= FRESH_DAYS:
        return "fresh"
    return "aging"


class Scored(BaseModel):
    """The scored figure: tier + interval + freshness + provenance dates."""

    confidence: str
    confidence_interval: Interval
    freshness: str
    as_of_date: str | None
    next_expected_update: str | None


def score_edge(
    *,
    interval: Interval,
    n_independent_sources: int,
    estimated: bool = False,
    exact_from_primary: bool = False,
    as_of: date | None = None,
    next_expected_update: date | None = None,
    today: date | None = None,
) -> Scored:
    today = today or date.today()
    return Scored(
        confidence=confidence_tier(
            n_independent_sources=n_independent_sources,
            estimated=estimated,
            exact_from_primary=exact_from_primary,
        ),
        confidence_interval=interval,
        freshness=freshness(as_of=as_of, next_expected_update=next_expected_update, today=today),
        as_of_date=as_of.isoformat() if as_of else None,
        next_expected_update=next_expected_update.isoformat() if next_expected_update else None,
    )
