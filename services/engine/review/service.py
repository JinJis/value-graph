"""Build Review — one read-only aggregation of EVERYTHING a theme has, for the pre-publish
review stage. It answers, at a glance: what data exists, how the supply chain actually
connects, and where it's empty (especially *why* trade edges are 0).

Pure read; no LLM, no mutation. It joins the per-company inputs (blueprint companies,
financials, calendar, tickets, sources) with the latest Staging build's outputs (claims,
publishable edges, gap edges) so the admin sees the whole picture in one place instead of
hopping across six steps.

The mental model it surfaces:

    Blueprint companies ──┬─ Financials (revenue/cost buckets)
                          ├─ Disclosure Calendar (next filing)
                          └─ Sources (documents / citations)
                                     │
                                     ▼
                                  Claims  ── extracted supplier→customer trades
                                     │
                                     ▼
                           Edges (publishable) + Gap edges (drawn ghosts)
                                     │
                                     ▼
                                  Publish

Edges exist ONLY where claims do — financials/calendar/tickets quantify and date a trade,
they never create one. So a build with 0 claims has 0 edges no matter how full the other
boxes are; this report makes that break-point visible.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from services.engine.blueprint.models import BlueprintRecord
from services.engine.calendar.repository import CalendarRepository
from services.engine.db.graph_store import GraphStore
from services.engine.financials.repository import FinancialsRepository
from services.engine.themes.models import SourceRecord
from services.engine.tickets.repository import TicketRepository

# Financial buckets shown per company (revenue is the CVE denominator; the rest are the
# complementary cost side). Order matters for display.
_FINANCIAL_BUCKETS: tuple[str, ...] = ("revenue", "cogs", "capex", "rnd", "sga")


class CompanyReview(BaseModel):
    """One company's data coverage + how it sits in the built graph."""

    ticker: str
    name: str
    role: str | None = None
    has_financials: bool = False  # revenue present (the denominator the CVE needs)
    financials_buckets: list[str] = Field(default_factory=list)  # which buckets are filled
    has_calendar: bool = False  # a next_expected_update is set
    next_update: str | None = None
    claims: int = 0  # claims mentioning this company (either side)
    out_edges: int = 0  # publishable edges where it is the supplier
    in_edges: int = 0  # publishable edges where it is the customer
    gap_edges: int = 0  # gap (ghost) edges it appears in
    open_tickets: int = 0  # OPEN tickets targeting it


class RelationshipReview(BaseModel):
    """One supplier→customer relationship the build produced, with its state + provenance."""

    supplier: str
    customer: str
    # publishable | estimated | conflict (these three are admitted edges) | gap (a ghost).
    state: str
    customer_cost_share: float | None = None
    confidence: str | None = None
    freshness: str | None = None
    interval_low: float | None = None
    interval_high: float | None = None
    n_sources: int = 0
    as_of: str | None = None
    reason: str | None = None  # why a gap edge isn't publishable


class ReviewCounts(BaseModel):
    """The ERD boxes — one count per entity in the build pipeline."""

    companies: int = 0
    financials_covered: int = 0
    calendar_covered: int = 0
    source_documents: int = 0  # uploaded files (feed claim extraction)
    source_citations: int = 0  # URL-only (no stored text to extract)
    claims: int = 0
    publishable_edges: int = 0
    gap_edges: int = 0
    estimated_edges: int = 0
    open_tickets: int = 0


class ThemeReview(BaseModel):
    theme_id: str
    has_blueprint: bool
    has_build: bool
    build_version: int | None = None
    completeness: float = 0.0
    counts: ReviewCounts
    companies: list[CompanyReview] = Field(default_factory=list)
    relationships: list[RelationshipReview] = Field(default_factory=list)


def _company_parts(target: str) -> list[str]:
    """A ticket target is either a company ticker or an edge ``A->B``; return the company
    ticker(s) it touches so tickets count toward the right rows."""
    if "->" in target:
        return [p.strip() for p in target.split("->", 1) if p.strip()]
    return [target.strip()] if target.strip() else []


def _edge_state(edge: dict[str, Any], reconciliation: dict[str, Any] | None) -> str:
    if (reconciliation or {}).get("status") == "conflict":
        return "conflict"
    if edge.get("confidence") == "estimated":
        return "estimated"
    return "publishable"


def build_theme_review(
    *,
    theme_id: str,
    blueprint: BlueprintRecord | None,
    sources: list[SourceRecord],
    financials_repo: FinancialsRepository,
    calendar_repo: CalendarRepository | None,
    tickets_repo: TicketRepository,
    graph_store: GraphStore,
) -> ThemeReview:
    """Join every per-theme input with the latest Staging build into one review object."""
    companies = blueprint.companies if blueprint is not None else []
    tickers = [c.ticker for c in companies]
    ticker_set = set(tickers)

    financials = {r.company_ticker: r for r in financials_repo.list_for(tickers)} if tickers else {}
    calendar = {}
    if calendar_repo is not None:
        calendar = {
            e.company_ticker: e
            for e in calendar_repo.list_all()
            if e.company_ticker in ticker_set
        }

    open_tickets = [t for t in tickets_repo.list_tickets(theme_id) if t.status == "OPEN"]
    tickets_by_company: dict[str, int] = {}
    for ticket in open_tickets:
        for part in _company_parts(ticket.target):
            tickets_by_company[part] = tickets_by_company.get(part, 0) + 1

    build = graph_store.load_latest(theme_id)
    edges = build.edges if build is not None else []
    gap_edges = build.gap_edges if build is not None else []
    claims = build.claims if build is not None else []
    edge_details = build.edge_details if build is not None else {}

    claims_by_company: dict[str, int] = {}
    for claim in claims:
        for side in (claim.get("subject"), claim.get("object")):
            if side:
                claims_by_company[side] = claims_by_company.get(side, 0) + 1

    out_by_company: dict[str, int] = {}
    in_by_company: dict[str, int] = {}
    for edge in edges:
        out_by_company[edge["supplier"]] = out_by_company.get(edge["supplier"], 0) + 1
        in_by_company[edge["customer"]] = in_by_company.get(edge["customer"], 0) + 1
    gaps_by_company: dict[str, int] = {}
    for gap in gap_edges:
        gaps_by_company[gap.supplier] = gaps_by_company.get(gap.supplier, 0) + 1
        gaps_by_company[gap.customer] = gaps_by_company.get(gap.customer, 0) + 1

    company_rows: list[CompanyReview] = []
    for company in companies:
        record = financials.get(company.ticker)
        buckets = [
            b for b in _FINANCIAL_BUCKETS if record is not None and getattr(record, b) is not None
        ]
        entry = calendar.get(company.ticker)
        next_update = (
            entry.next_filing_estimate.isoformat()
            if entry is not None and entry.next_filing_estimate is not None
            else None
        )
        company_rows.append(
            CompanyReview(
                ticker=company.ticker,
                name=company.name,
                role=company.role,
                has_financials=record is not None and record.revenue is not None,
                financials_buckets=buckets,
                has_calendar=next_update is not None,
                next_update=next_update,
                claims=claims_by_company.get(company.ticker, 0),
                out_edges=out_by_company.get(company.ticker, 0),
                in_edges=in_by_company.get(company.ticker, 0),
                gap_edges=gaps_by_company.get(company.ticker, 0),
                open_tickets=tickets_by_company.get(company.ticker, 0),
            )
        )

    relationships: list[RelationshipReview] = []
    estimated = 0
    for edge in edges:
        key = f"{edge['supplier']}->{edge['customer']}"
        reconciliation = (edge_details.get(key) or {}).get("reconciliation")
        interval = edge.get("confidence_interval") or {}
        state = _edge_state(edge, reconciliation)
        if state == "estimated":
            estimated += 1
        relationships.append(
            RelationshipReview(
                supplier=edge["supplier"],
                customer=edge["customer"],
                state=state,
                customer_cost_share=edge.get("customer_cost_share"),
                confidence=edge.get("confidence"),
                freshness=edge.get("freshness"),
                interval_low=interval.get("low"),
                interval_high=interval.get("high"),
                n_sources=int((reconciliation or {}).get("n_sources") or 0),
                as_of=edge.get("as_of_date"),
            )
        )
    for gap in gap_edges:
        if gap.confidence == "estimated":
            estimated += 1
        relationships.append(
            RelationshipReview(
                supplier=gap.supplier,
                customer=gap.customer,
                state="gap",
                confidence=gap.confidence,
                freshness=gap.freshness,
                reason=gap.reason,
            )
        )

    documents = sum(1 for s in sources if s.storage_key)
    total_edges = len(edges) + len(gap_edges)
    counts = ReviewCounts(
        companies=len(companies),
        financials_covered=sum(1 for c in company_rows if c.has_financials),
        calendar_covered=sum(1 for c in company_rows if c.has_calendar),
        source_documents=documents,
        source_citations=len(sources) - documents,
        claims=len(claims),
        publishable_edges=len(edges),
        gap_edges=len(gap_edges),
        estimated_edges=estimated,
        open_tickets=len(open_tickets),
    )

    return ThemeReview(
        theme_id=theme_id,
        has_blueprint=blueprint is not None,
        has_build=build is not None,
        build_version=build.version if build is not None else None,
        completeness=(len(edges) / total_edges) if total_edges else 0.0,
        counts=counts,
        companies=company_rows,
        relationships=relationships,
    )
