"""[M2-GEN-01] Gap -> ticket generation: one per data point, idempotent, no dupes."""

from __future__ import annotations

import json
import re

from services.engine.blueprint.models import Blueprint, BlueprintCompany
from services.engine.llm.router import DEFAULT_MODELS, LLMRouter
from services.engine.themes.models import Theme, ThemeCreate
from services.engine.themes.repository import InMemoryThemeRepository
from services.engine.tickets.generate import generate_tickets
from services.engine.tickets.repository import InMemoryTicketRepository


def _theme(name: str = "AI Data Centers") -> Theme:
    return InMemoryThemeRepository().create_theme(ThemeCreate(name=name))


class _EnrichFake:
    """Returns one canned description per ref it finds in the enrichment prompt."""

    def generate_text(self, *, model: str, prompt: str) -> str:
        refs = re.findall(r"\[(P\d+)\]", prompt)
        return json.dumps(
            {"points": [{"ref": r, "description": f"Detailed brief for {r}"} for r in refs]}
        )


def _company(ticker: str, required_data_points: list[str]) -> BlueprintCompany:
    return BlueprintCompany(
        ticker=ticker,
        name=f"Name {ticker}",
        country="US",
        role="supplier",
        required_data_points=required_data_points,
    )


def _blueprint(companies: list[BlueprintCompany]) -> Blueprint:
    return Blueprint(theme_id="t1", version=1, companies=companies)


def test_one_ticket_per_required_data_point() -> None:
    blueprint = _blueprint([_company("A", ["revenue", "cogs"]), _company("B", ["capex"])])
    repo = InMemoryTicketRepository()
    result = generate_tickets("t1", blueprint, repo)
    assert result.created == 3 and result.skipped == 0
    tickets = repo.list_tickets("t1")
    assert {(t.target, t.metric) for t in tickets} == {
        ("A", "revenue"),
        ("A", "cogs"),
        ("B", "capex"),
    }
    assert all(t.status == "OPEN" for t in tickets)


def test_rerun_is_idempotent() -> None:
    blueprint = _blueprint([_company("A", ["revenue"])])
    repo = InMemoryTicketRepository()
    generate_tickets("t1", blueprint, repo)
    again = generate_tickets("t1", blueprint, repo)
    assert again.created == 0 and again.skipped == 1
    assert len(repo.list_tickets("t1")) == 1


def test_duplicate_metric_yields_one_ticket() -> None:
    blueprint = _blueprint([_company("A", ["revenue", "revenue"])])
    result = generate_tickets("t1", blueprint, InMemoryTicketRepository())
    assert result.created == 1 and result.skipped == 1


def test_company_without_data_points_yields_no_tickets() -> None:
    result = generate_tickets("t1", _blueprint([_company("A", [])]), InMemoryTicketRepository())
    assert result.created == 0 and result.skipped == 0


def test_descriptions_enriched_by_router() -> None:
    blueprint = _blueprint([_company("A", ["revenue"]), _company("B", ["capex"])])
    repo = InMemoryTicketRepository()
    result = generate_tickets(
        "t1", blueprint, repo, theme=_theme(), router=LLMRouter(_EnrichFake(), DEFAULT_MODELS)
    )
    assert result.created == 2
    reasons = {t.metric: (t.reason or "") for t in repo.list_tickets("t1")}
    assert reasons["revenue"].startswith("Detailed brief")  # cheap-model research brief
    assert reasons["capex"].startswith("Detailed brief")


def test_fallback_description_without_router() -> None:
    repo = InMemoryTicketRepository()
    generate_tickets("t1", _blueprint([_company("A", ["revenue"])]), repo)  # no theme/router
    reason = repo.list_tickets("t1")[0].reason or ""
    assert "Find 'revenue' for" in reason and "value chain" in reason  # richer than before


class _BadFake:
    def generate_text(self, *, model: str, prompt: str) -> str:
        return "not json at all"


def test_enrich_failure_falls_back_to_template() -> None:
    repo = InMemoryTicketRepository()
    generate_tickets(
        "t1",
        _blueprint([_company("A", ["revenue"])]),
        repo,
        theme=_theme(),
        router=LLMRouter(_BadFake(), DEFAULT_MODELS),
    )
    reason = repo.list_tickets("t1")[0].reason or ""
    assert "Find 'revenue' for" in reason  # LLM unusable -> deterministic template
