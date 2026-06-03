"""[M3-EST-05] S5 VSCA-est: estimated edges with a wide interval and an auto-ticket."""

from __future__ import annotations

import json
import os

import pytest

from services.engine.cve.estimate import MIN_REL_WIDTH, estimate_edge, widen
from services.engine.llm.router import LLMRouter
from services.engine.tickets.repository import InMemoryTicketRepository


class FakeGenerator:
    def __init__(self, *responses: str) -> None:
        self._responses = list(responses) or [""]
        self.calls = 0

    def generate_text(self, *, model: str, prompt: str) -> str:
        response = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return response


def _router(*responses: str) -> LLMRouter:
    return LLMRouter.from_env(env={}, generator=FakeGenerator(*responses))


def _estimate_json(value: float, low: float, high: float, method: str = "prior") -> str:
    return json.dumps(
        {"value": value, "low": low, "high": high, "method": method, "rationale": "peer analogy"}
    )


def test_qualitative_relationship_yields_estimated_edge_with_ticket() -> None:
    repo = InMemoryTicketRepository()
    estimate = estimate_edge(
        supplier="TSM",
        customer="NVDA",
        metric="customer_cost_share",
        product="wafers",
        router=_router(_estimate_json(8, 4, 12, "peer")),
        theme_id="t1",
        ticket_repo=repo,
    )
    assert estimate.confidence == "estimated"
    assert estimate.point == 8.0
    assert estimate.interval.low <= 8 <= estimate.interval.high
    assert estimate.method == "peer"

    tickets = repo.list_tickets("t1")
    assert len(tickets) == 1
    assert tickets[0].target == "TSM->NVDA"
    assert tickets[0].metric == "estimate:customer_cost_share"


def test_confidence_never_higher_than_estimated() -> None:
    # The model output even claims "verified"; the engine hardcodes "estimated".
    response = json.dumps(
        {"value": 5, "low": 4, "high": 6, "method": "prior", "confidence": "verified"}
    )
    estimate = estimate_edge(supplier="A", customer="B", metric="m", router=_router(response))
    assert estimate.confidence == "estimated"


def test_narrow_interval_is_widened() -> None:
    estimate = estimate_edge(
        supplier="A", customer="B", metric="m", router=_router(_estimate_json(10, 9.9, 10.1))
    )
    width = estimate.interval.high - estimate.interval.low
    assert width >= MIN_REL_WIDTH * 10 - 1e-9  # widened to >= 50% of the point
    assert estimate.interval.low <= 10 <= estimate.interval.high


def test_widen_keeps_point_inside_and_nonnegative() -> None:
    inside = widen(2.0, 5.0, 6.0)  # point below the given range
    assert inside.low <= 2.0 <= inside.high and inside.low >= 0.0
    clamped = widen(1.0, -5.0, 0.5)  # negative low clamped to 0
    assert clamped.low == 0.0 and clamped.high >= 1.0


def test_no_ticket_without_repo() -> None:
    estimate = estimate_edge(
        supplier="A", customer="B", metric="m", router=_router(_estimate_json(5, 3, 7))
    )
    assert estimate.confidence == "estimated"


def test_retry_then_parse() -> None:
    estimate = estimate_edge(
        supplier="A", customer="B", metric="m", router=_router("garbage", _estimate_json(5, 3, 7))
    )
    assert estimate.point == 5.0


@pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"),
    reason="no GOOGLE_API_KEY; skipping live DEEP estimation",
)
def test_live_estimate_is_estimated_and_wide() -> None:
    estimate = estimate_edge(
        supplier="TSMC",
        customer="NVIDIA",
        metric="customer_cost_share",
        product="wafers",
        router=LLMRouter.from_env(),
    )
    assert estimate.confidence == "estimated"
    assert estimate.interval.low <= estimate.point <= estimate.interval.high
    width = estimate.interval.high - estimate.interval.low
    assert width >= MIN_REL_WIDTH * abs(estimate.point) - 1e-9
