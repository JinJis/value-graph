"""[M3-SCORE-06] S6 scoring: confidence tier + freshness + next_expected_update."""

from __future__ import annotations

from datetime import date

from services.engine.cve.reconcile import Interval
from services.engine.cve.score import confidence_tier, freshness, score_edge

TODAY = date(2026, 6, 1)


def _interval() -> Interval:
    return Interval(low=8.0, high=11.0)


def test_tier_verified_with_two_independent_sources() -> None:
    assert confidence_tier(n_independent_sources=2, estimated=False) == "verified"


def test_tier_verified_via_exact_math_from_primary() -> None:
    assert (
        confidence_tier(n_independent_sources=1, estimated=False, exact_from_primary=True)
        == "verified"
    )


def test_tier_derived_with_single_source() -> None:
    assert confidence_tier(n_independent_sources=1, estimated=False) == "derived"


def test_tier_estimated_flag_wins() -> None:
    assert confidence_tier(n_independent_sources=3, estimated=True) == "estimated"


def test_tier_estimated_with_zero_sources() -> None:
    assert confidence_tier(n_independent_sources=0, estimated=False) == "estimated"


def test_freshness_gap_when_no_as_of() -> None:
    assert freshness(as_of=None, next_expected_update=None, today=TODAY) == "gap"


def test_freshness_fresh_within_30_days() -> None:
    assert (
        freshness(as_of=date(2026, 5, 20), next_expected_update=date(2026, 8, 15), today=TODAY)
        == "fresh"
    )


def test_freshness_aging_old_but_not_past_next() -> None:
    assert (
        freshness(as_of=date(2026, 3, 1), next_expected_update=date(2026, 8, 15), today=TODAY)
        == "aging"
    )


def test_freshness_stale_past_next_expected() -> None:
    assert (
        freshness(as_of=date(2026, 3, 1), next_expected_update=date(2026, 5, 15), today=TODAY)
        == "stale"
    )


def test_score_edge_carries_all_fields() -> None:
    scored = score_edge(
        interval=_interval(),
        n_independent_sources=2,
        as_of=date(2026, 5, 20),
        next_expected_update=date(2026, 8, 15),
        today=TODAY,
    )
    assert scored.confidence == "verified"
    assert scored.confidence_interval.low == 8.0 and scored.confidence_interval.high == 11.0
    assert scored.freshness == "fresh"
    assert scored.as_of_date == "2026-05-20"
    assert scored.next_expected_update == "2026-08-15"


def test_score_edge_estimated_with_gap() -> None:
    scored = score_edge(
        interval=_interval(), n_independent_sources=0, estimated=True, as_of=None, today=TODAY
    )
    assert scored.confidence == "estimated"
    assert scored.freshness == "gap"
    assert scored.next_expected_update is None
