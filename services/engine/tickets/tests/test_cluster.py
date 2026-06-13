"""Ticket clustering: light-model grouping with a deterministic fallback + size cap."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from services.engine.llm.router import DEFAULT_MODELS, LLMRouter, Tier
from services.engine.tickets.cluster import cluster_tickets
from services.engine.tickets.models import Ticket


def _ticket(target: str, metric: str) -> Ticket:
    now = datetime.now(UTC)
    return Ticket(
        id=f"{target}:{metric}",
        theme_id="t",
        target=target,
        metric=metric,
        reason=None,
        status="OPEN",
        reason_code=None,
        current_estimate=None,
        created_at=now,
        updated_at=now,
    )


class _Gen:
    """Light-model fake: returns a clustering plan when asked, else empty."""

    def __init__(self, plan: object | None) -> None:
        self._plan = plan

    def generate_text(self, *, model: str, prompt: str) -> str:
        return json.dumps(self._plan) if self._plan is not None else ""


def _router(plan: object | None) -> LLMRouter:
    return LLMRouter(_Gen(plan), DEFAULT_MODELS)


def test_llm_clusters_group_by_plan() -> None:
    tickets = [_ticket("NVDA", "revenue"), _ticket("TSM", "revenue"), _ticket("NVDA", "cogs")]
    # Group the two "revenue" tickets (T1,T2); keep cogs (T3) separate.
    router = _router({"clusters": [["T1", "T2"], ["T3"]]})
    clusters = cluster_tickets(tickets, router, tier=Tier.LOW)
    assert sorted(len(c) for c in clusters) == [1, 2]
    pair = next(c for c in clusters if len(c) == 2)
    assert {t.metric for t in pair} == {"revenue"}


def test_dropped_refs_become_a_leftover_cluster() -> None:
    tickets = [_ticket("A", "m"), _ticket("B", "m"), _ticket("C", "m")]
    router = _router({"clusters": [["T1"]]})  # model forgot T2, T3
    clusters = cluster_tickets(tickets, router, tier=Tier.LOW)
    assert sum(len(c) for c in clusters) == 3  # every ticket still placed


def test_fallback_groups_by_metric_when_model_unusable() -> None:
    tickets = [
        _ticket("A", "revenue"),
        _ticket("B", "revenue"),
        _ticket("C", "cogs"),
    ]
    clusters = cluster_tickets(tickets, _router(None), tier=Tier.LOW)  # empty -> fallback
    assert sorted(len(c) for c in clusters) == [1, 2]


def test_clusters_are_capped_at_max_size() -> None:
    tickets = [_ticket(f"C{i}", "revenue") for i in range(25)]
    clusters = cluster_tickets(tickets, _router(None), tier=Tier.LOW, max_size=10)
    assert all(len(c) <= 10 for c in clusters)
    assert sum(len(c) for c in clusters) == 25


def test_single_ticket_is_one_cluster() -> None:
    one = _ticket("A", "m")
    assert cluster_tickets([one], _router(None)) == [[one]]
    assert cluster_tickets([], _router(None)) == []
