"""Build Review aggregation: per-company coverage + relationships from the latest build."""

from __future__ import annotations

from datetime import UTC, date, datetime

from services.engine.blueprint.models import Blueprint, BlueprintCompany, BlueprintRecord
from services.engine.blueprint.repository import InMemoryBlueprintRepository
from services.engine.calendar.models import CalendarUpsert
from services.engine.calendar.repository import InMemoryCalendarRepository
from services.engine.db.graph_store import InMemoryGraphStore
from services.engine.db.persist import persist_cve_run
from services.engine.db.tests.test_artifacts import _state
from services.engine.financials.models import FinancialsUpsert
from services.engine.financials.repository import InMemoryFinancialsRepository
from services.engine.review.service import build_theme_review
from services.engine.themes.models import SourceCreate, SourceRecord
from services.engine.tickets.models import TicketCreate
from services.engine.tickets.repository import InMemoryTicketRepository

THEME = "theme-1"  # _state() uses theme-1


def _blueprint() -> BlueprintRecord:
    repo = InMemoryBlueprintRepository()
    return repo.save(
        Blueprint(
            theme_id=THEME,
            version=1,
            companies=[
                # country="US" keeps tickers bare so they match _state()'s raw tickers (in a
                # real run the CVE resolves mentions to these canonical blueprint tickers).
                BlueprintCompany(ticker="INTC", name="Intel", country="US", role="supplier"),
                BlueprintCompany(ticker="HPQ", name="HP Inc.", country="US", role="customer"),
                BlueprintCompany(ticker="TSM", name="TSMC", country="US", role="foundry"),
                BlueprintCompany(ticker="NVDA", name="NVIDIA", country="US", role="customer"),
            ],
        )
    )


def _source(sid: str, *, storage_key: str | None) -> SourceRecord:
    create = SourceCreate(type="filing", url="https://x", storage_key=storage_key)
    return SourceRecord(
        id=sid,
        theme_id=THEME,
        created_at=datetime.now(UTC),
        verification_status="unverified",
        **create.model_dump(),
    )


def test_review_joins_inputs_with_build_outputs() -> None:
    graph = InMemoryGraphStore()
    persist_cve_run(_state(), graph)  # 1 publishable (INTC->HPQ) + 1 gap (TSM->NVDA)

    fin = InMemoryFinancialsRepository()
    fin.upsert(FinancialsUpsert(company_ticker="INTC", revenue=100.0, cogs=80.0))
    # HPQ has cost only, no revenue -> not "covered".
    fin.upsert(FinancialsUpsert(company_ticker="HPQ", cogs=221.0))

    cal = InMemoryCalendarRepository()
    cal.upsert(CalendarUpsert(company_ticker="INTC", next_filing_estimate=date(2026, 8, 15)))

    tickets = InMemoryTicketRepository()
    tickets.create_open_ticket(THEME, TicketCreate(target="TSM->NVDA", metric="gap:estimated"))
    tickets.create_open_ticket(THEME, TicketCreate(target="NVDA", metric="entity-resolution"))

    review = build_theme_review(
        theme_id=THEME,
        blueprint=_blueprint(),
        sources=[_source("doc", storage_key="k1"), _source("cite", storage_key=None)],
        financials_repo=fin,
        calendar_repo=cal,
        tickets_repo=tickets,
        graph_store=graph,
    )

    assert review.has_build and review.build_version == 1
    c = review.counts
    assert c.companies == 4
    assert c.financials_covered == 1  # only INTC has revenue
    assert c.calendar_covered == 1
    assert c.source_documents == 1 and c.source_citations == 1
    assert c.publishable_edges == 1 and c.gap_edges == 1 and c.estimated_edges == 1
    assert c.open_tickets == 2

    by_ticker = {r.ticker: r for r in review.companies}
    assert by_ticker["INTC"].has_financials and by_ticker["INTC"].financials_buckets == [
        "revenue",
        "cogs",
    ]
    assert by_ticker["INTC"].out_edges == 1 and by_ticker["INTC"].in_edges == 0
    assert by_ticker["HPQ"].has_financials is False  # cost only, no revenue
    assert by_ticker["HPQ"].in_edges == 1
    # TSM->NVDA is a gap edge; both appear in gap counts, and the ticket targets touch both.
    assert by_ticker["TSM"].gap_edges == 1 and by_ticker["NVDA"].gap_edges == 1
    assert by_ticker["NVDA"].open_tickets == 2  # gap:estimated (TSM->NVDA) + entity-resolution

    states = {(r.supplier, r.customer): r for r in review.relationships}
    assert states[("INTC", "HPQ")].state == "publishable"
    assert states[("INTC", "HPQ")].n_sources == 1
    assert states[("TSM", "NVDA")].state == "gap"
    assert states[("TSM", "NVDA")].reason  # explains why it's a ghost


def test_review_with_no_build_is_empty_but_lists_companies() -> None:
    review = build_theme_review(
        theme_id="empty",
        blueprint=_blueprint(),
        sources=[],
        financials_repo=InMemoryFinancialsRepository(),
        calendar_repo=InMemoryCalendarRepository(),
        tickets_repo=InMemoryTicketRepository(),
        graph_store=InMemoryGraphStore(),
    )
    assert review.has_build is False and review.build_version is None
    assert review.counts.companies == 4
    assert review.counts.claims == 0 and review.counts.publishable_edges == 0
    assert review.relationships == []
    assert all(c.claims == 0 and c.out_edges == 0 for c in review.companies)
