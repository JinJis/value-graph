"""[M3-REC-04] S4 reconciliation: conflicts flagged (never averaged), conservation,
10% bound, and an interval on every output."""

from __future__ import annotations

import pytest

from services.engine.cve.reconcile import (
    Estimate,
    apply_upper_bound,
    check_conservation,
    reconcile,
    reconcile_and_ticket,
)
from services.engine.tickets.repository import InMemoryTicketRepository


def _est(value: float, source_id: str) -> Estimate:
    return Estimate(value=value, source_id=source_id)


def test_single_estimate_has_point_and_interval() -> None:
    result = reconcile([_est(9.5, "s1")])
    assert result.status == "reconciled"
    assert result.point == 9.5
    assert result.interval.low < 9.5 < result.interval.high  # single-source band


def test_agreeing_estimates_reconcile_to_median() -> None:
    result = reconcile([_est(9.5, "a"), _est(9.6, "b"), _est(9.4, "c")])
    assert result.status == "reconciled"
    assert result.point == 9.5  # median, not mean
    assert result.interval.low == 9.4 and result.interval.high == 9.6
    assert result.n_sources == 3


def test_conflicting_estimates_are_flagged_not_averaged() -> None:
    result = reconcile([_est(9.5, "a"), _est(15.0, "b")])
    assert result.status == "conflict"
    assert result.point is None  # NOT averaged (would be ~12.25)
    assert result.interval.low == 9.5 and result.interval.high == 15.0
    assert result.reason


def test_conflict_creates_ticket() -> None:
    repo = InMemoryTicketRepository()
    result = reconcile_and_ticket(
        [_est(9.5, "a"), _est(20.0, "b")],
        edge_target="INTC->HPQ",
        metric="customer_cost_share",
        theme_id="t1",
        ticket_repo=repo,
    )
    assert result.status == "conflict"
    tickets = repo.list_tickets("t1")
    assert len(tickets) == 1
    assert tickets[0].target == "INTC->HPQ"
    assert tickets[0].metric == "conflict:customer_cost_share"


def test_agreement_creates_no_ticket() -> None:
    repo = InMemoryTicketRepository()
    reconcile_and_ticket(
        [_est(9.5, "a"), _est(9.55, "b")],
        edge_target="X",
        metric="m",
        theme_id="t1",
        ticket_repo=repo,
    )
    assert repo.list_tickets("t1") == []


def test_conservation_ok_under_capacity() -> None:
    result = check_conservation([30, 40, 20])
    assert result.ok and not result.flagged
    assert result.scale == 1.0 and result.scaled == [30, 40, 20]


def test_conservation_violation_downscales() -> None:
    result = check_conservation([60, 60, 40])  # sum 160 > 100
    assert not result.ok and result.flagged
    assert result.scale == pytest.approx(100 / 160)
    assert sum(result.scaled) == pytest.approx(100.0)


def test_apply_upper_bound_caps_interval() -> None:
    capped = apply_upper_bound(reconcile([_est(8.0, "a")]), 10.0)
    assert capped.status == "reconciled" and capped.point == 8.0
    assert capped.interval.high <= 10.0


def test_apply_upper_bound_conflict_when_point_exceeds() -> None:
    capped = apply_upper_bound(reconcile([_est(12.0, "a")]), 10.0)  # point 12 > 10
    assert capped.status == "conflict" and capped.point is None
    assert capped.interval.high == 10.0
    assert capped.reason


def test_every_output_carries_an_interval() -> None:
    for result in (
        reconcile([_est(5, "a")]),
        reconcile([_est(5, "a"), _est(5.1, "b")]),
        reconcile([_est(5, "a"), _est(50, "b")]),  # conflict
    ):
        assert result.interval.low <= result.interval.high
