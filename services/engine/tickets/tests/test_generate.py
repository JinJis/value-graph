"""[M2-GEN-01] Gap -> ticket generation: one per data point, idempotent, no dupes."""

from __future__ import annotations

from services.engine.blueprint.models import Blueprint, BlueprintCompany
from services.engine.tickets.generate import generate_tickets
from services.engine.tickets.repository import InMemoryTicketRepository


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
