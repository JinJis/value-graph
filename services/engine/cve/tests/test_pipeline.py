"""[M3-ORCH-08] End-to-end CVE pipeline: S0-S7 wired, idempotent, run persisted."""

from __future__ import annotations

import json

from services.engine.cve.gaps import GAP_METRIC_PREFIX, GapType
from services.engine.cve.pipeline import (
    CVEDeps,
    CVEResult,
    Document,
    run_cve,
)
from services.engine.cve.resolve import CanonicalCompany, LLMAdjudicator, Resolver
from services.engine.cve.run_repository import DONE, InMemoryCveRunRepository
from services.engine.llm.router import LLMRouter
from services.engine.tickets.repository import InMemoryTicketRepository

TODAY = "2026-06-01"

# Worked CVE example: Intel discloses 21% of revenue from HP -> trade = 0.21*Rev_INTC;
# with HP COGS = 221, customer_cost_share = 100*21/221 ~= 9.5%.
DOC_DISCLOSED = Document(
    source_id="src-intc",
    text="Intel reported that 21% of its revenue came from HP Inc. in fiscal 2026.",
    as_of="2026-05-20",
)
# A qualitative-only relationship -> no number -> VSCA-est -> estimated + gap ticket.
DOC_QUALITATIVE = Document(
    source_id="src-tsm",
    text="TSMC supplies advanced wafers to NVIDIA for its GPUs.",
    as_of="2026-05-22",
)

FINANCIALS = {"INTC": {"revenue": 100.0}, "HPQ": {"COGS": 221.0}}
CALENDAR = {"INTC": "2026-08-15"}


class ScriptedGenerator:
    """Content-aware fake: returns claims for extract, an estimate for VSCA-est."""

    def generate_text(self, *, model: str, prompt: str) -> str:
        if "METRIC TO ESTIMATE" in prompt:  # S5 estimate_edge
            return json.dumps(
                {"value": 8, "low": 4, "high": 12, "method": "peer", "rationale": "analogy"}
            )
        if "Which company does the mention" in prompt:  # S2 adjudication (unused here)
            return "NONE"
        if "came from HP" in prompt:  # S1 extract — disclosed supplier-side claim
            return json.dumps(
                {
                    "claims": [
                        {
                            "relation": "supplier_revenue_share",
                            "subject": "Intel",
                            "object": "HP Inc.",
                            "value": 21,
                            "unit": "%",
                            "cost_bucket": "COGS",
                            "text_span": "21% of its revenue came from HP Inc.",
                        }
                    ]
                }
            )
        if "wafers" in prompt:  # S1 extract — qualitative claim
            return json.dumps(
                {
                    "claims": [
                        {
                            "relation": "qualitative",
                            "subject": "TSMC",
                            "object": "NVIDIA",
                            "value": None,
                            "unit": None,
                            "cost_bucket": None,
                            "text_span": "TSMC supplies advanced wafers to NVIDIA",
                        }
                    ]
                }
            )
        return ""


def _deps(ticket_repo: InMemoryTicketRepository) -> CVEDeps:
    router = LLMRouter.from_env(env={}, generator=ScriptedGenerator())
    companies = [
        CanonicalCompany(ticker="INTC", name="Intel"),
        CanonicalCompany(ticker="HPQ", name="HP Inc."),
        CanonicalCompany(ticker="TSM", name="TSMC", aliases=("Taiwan Semiconductor",)),
        CanonicalCompany(ticker="NVDA", name="NVIDIA"),
    ]
    resolver = Resolver(companies=companies, adjudicator=LLMAdjudicator(router=router))
    return CVEDeps(router=router, resolver=resolver, ticket_repo=ticket_repo)


def _run(
    ticket_repo: InMemoryTicketRepository, run_repo: InMemoryCveRunRepository | None = None
) -> CVEResult:
    return run_cve(
        theme_id="theme-1",
        deps=_deps(ticket_repo),
        documents=[DOC_DISCLOSED, DOC_QUALITATIVE],
        financials=FINANCIALS,
        calendar=CALENDAR,
        today=TODAY,
        run_repo=run_repo,
    )


def test_pipeline_runs_end_to_end() -> None:
    tickets = InMemoryTicketRepository()
    result = _run(tickets)
    edges = result.state.edges

    assert set(edges) == {"INTC->HPQ", "TSM->NVDA"}

    # Disclosed edge: derived from one filing, quantified with confidence + interval.
    disclosed = edges["INTC->HPQ"]
    assert disclosed.reconciled is not None and disclosed.reconciled.point is not None
    assert abs(disclosed.reconciled.point - 9.502) < 0.05
    assert disclosed.estimated is False
    assert disclosed.scored is not None
    assert disclosed.scored.confidence == "derived"
    assert disclosed.scored.freshness == "fresh"
    assert disclosed.scored.as_of_date == "2026-05-20"
    assert disclosed.scored.next_expected_update == "2026-08-15"
    assert disclosed.assessment is not None

    # Qualitative edge: VSCA-est -> estimated, wide interval, point inside.
    estimated = edges["TSM->NVDA"]
    assert estimated.estimated is True
    assert estimated.scored is not None and estimated.scored.confidence == "estimated"
    assert estimated.reconciled is not None and estimated.reconciled.point is not None
    lo, hi = estimated.reconciled.interval.low, estimated.reconciled.interval.high
    assert lo <= estimated.reconciled.point <= hi


def test_estimated_edge_emits_gap_ticket() -> None:
    tickets = InMemoryTicketRepository()
    _run(tickets)
    open_tickets = tickets.list_tickets("theme-1")

    gap_estimated = f"{GAP_METRIC_PREFIX}{GapType.ESTIMATED.value}"
    matches = [t for t in open_tickets if t.target == "TSM->NVDA" and t.metric == gap_estimated]
    assert len(matches) == 1
    assert matches[0].status == "OPEN"

    # The disclosed (derived, fresh) edge has no gap ticket.
    assert not [
        t
        for t in open_tickets
        if t.target == "INTC->HPQ" and t.metric.startswith(GAP_METRIC_PREFIX)
    ]


def test_pipeline_is_idempotent() -> None:
    tickets = InMemoryTicketRepository()
    first = _run(tickets)
    n_after_first = len(tickets.list_tickets("theme-1"))

    second = _run(tickets)
    n_after_second = len(tickets.list_tickets("theme-1"))

    # Same inputs -> same reconstructable state (edges/claims/resolutions) and no
    # duplicate tickets. The per-run `gap_results` log legitimately differs: run 1
    # OPENS the gap ticket; run 2 finds it already open and no-ops (the idempotent
    # sync). So compare the persistent state, not the action log.
    keep = {"edges", "claims", "resolutions"}
    first_state = first.state.model_dump(mode="json", include=keep)
    second_state = second.state.model_dump(mode="json", include=keep)
    assert first_state == second_state
    assert n_after_first == n_after_second
    # Run 2 opens nothing new (every gap ticket already exists).
    assert all(not r.opened for r in second.state.gap_results)


def test_run_is_persisted() -> None:
    tickets = InMemoryTicketRepository()
    runs = InMemoryCveRunRepository()
    result = _run(tickets, runs)

    assert result.run_id is not None
    record = runs.get(result.run_id)
    assert record is not None
    assert record.status == DONE
    assert record.trigger == "admin"
    assert record.state["edges"]  # full intermediate state persisted
    latest = runs.get_latest("theme-1")
    assert latest is not None and latest.id == result.run_id


def test_unknown_trigger_rejected() -> None:
    tickets = InMemoryTicketRepository()
    try:
        run_cve(
            theme_id="theme-1",
            deps=_deps(tickets),
            today=TODAY,
            trigger="forecast",  # not a valid trigger
        )
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "trigger" in str(exc)
