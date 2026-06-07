"""Run the CVE pipeline for a theme from its current Studio state.

Wires a theme's real inputs into :func:`run_cve` and persists the result as the next
versioned Staging build (the artifact :mod:`publish` consumes):

- documents: the theme's uploaded file Sources, decoded to text (URL-only citations
  carry no stored text, so they are skipped — the document-fetcher is a later seam);
- resolver: built from the approved blueprint's companies (mention -> ticker);
- calendar: the disclosure calendar feeds each figure's ``next_expected_update``;
- tickets: reflected via the pipeline's ticket side effects + the not-disclosed 10%
  bound applied during reconciliation.

``financials`` (market-data) is not yet fetched, so disclosures that need the
complementary side become VSCA-est (estimated) edges — drawn with intervals, ticketed.
"""

from __future__ import annotations

import logging
from datetime import date

from pydantic import BaseModel

from services.engine.blueprint.models import BlueprintRecord
from services.engine.calendar.repository import CalendarRepository, next_update_map
from services.engine.cve.pipeline import CVEDeps, Document, run_cve
from services.engine.cve.resolve import CanonicalCompany, LLMAdjudicator, Resolver
from services.engine.cve.run_repository import CveRunRepository
from services.engine.db.graph_store import GraphStore
from services.engine.db.persist import persist_cve_run
from services.engine.llm.router import LLMRouter
from services.engine.storage import Storage
from services.engine.themes.models import SourceRecord
from services.engine.tickets.repository import TicketRepository

logger = logging.getLogger("valuegraph.engine.cve.run")


class CveRunSummary(BaseModel):
    """What one CVE run produced (persisted as a Staging build for publish)."""

    run_id: str | None
    status: str
    build_version: int
    documents_ingested: int
    claims: int
    edges: int
    publishable_edges: int
    ghost_edges: int
    estimated_edges: int


def _documents(
    sources: list[SourceRecord], storage: Storage, *, fallback_as_of: str
) -> list[Document]:
    """Decode each uploaded file Source into a CVE :class:`Document` (best effort)."""
    docs: list[Document] = []
    for source in sources:
        if not source.storage_key:
            continue  # URL-only citation: no stored text to extract from
        try:
            raw = storage.load(source.storage_key)
        except Exception as exc:  # missing/unreadable blob — skip, don't fail the run
            logger.warning("cve.ingest skip source=%s: %s", source.id, exc)
            continue
        text = raw.decode("utf-8", "ignore").strip()
        if not text:
            continue
        as_of = source.as_of_date.isoformat() if source.as_of_date else fallback_as_of
        docs.append(Document(source_id=source.id, text=text, as_of=as_of))
    return docs


def run_cve_for_theme(
    *,
    theme_id: str,
    blueprint: BlueprintRecord,
    sources: list[SourceRecord],
    storage: Storage,
    router: LLMRouter,
    ticket_repo: TicketRepository,
    graph_store: GraphStore,
    run_repo: CveRunRepository,
    calendar_repo: CalendarRepository | None = None,
    today: str | None = None,
    trigger: str = "admin",
) -> CveRunSummary:
    """Run S0-S7 for ``theme_id`` over its current inputs and persist the next build."""
    today = today or date.today().isoformat()
    documents = _documents(sources, storage, fallback_as_of=today)
    companies = [
        CanonicalCompany(ticker=c.ticker, name=c.name) for c in blueprint.companies
    ]
    resolver = Resolver(companies=companies, adjudicator=LLMAdjudicator(router=router))
    deps = CVEDeps(router=router, resolver=resolver, ticket_repo=ticket_repo)
    tickers = [c.ticker for c in blueprint.companies]
    calendar = next_update_map(calendar_repo, tickers) if calendar_repo is not None else {}

    logger.info(
        "cve.run theme=%s documents=%d companies=%d calendar=%d trigger=%s",
        theme_id,
        len(documents),
        len(companies),
        len(calendar),
        trigger,
    )
    result = run_cve(
        theme_id=theme_id,
        deps=deps,
        documents=documents,
        financials={},  # market-data fetcher is a later seam; undisclosed -> VSCA-est
        calendar=calendar,
        today=today,
        trigger=trigger,
        run_repo=run_repo,
    )
    build = persist_cve_run(result.state, graph_store)
    estimated = sum(1 for e in result.state.edges.values() if e.estimated)
    logger.info(
        "cve.persisted theme=%s build=%s edges=%d publishable=%d ghost=%d claims=%d",
        theme_id,
        build.version,
        len(result.state.edges),
        len(build.edges),
        len(build.gap_edges),
        len(result.state.claims),
    )
    return CveRunSummary(
        run_id=result.run_id,
        status=result.status,
        build_version=build.version,
        documents_ingested=len(documents),
        claims=len(result.state.claims),
        edges=len(result.state.edges),
        publishable_edges=len(build.edges),
        ghost_edges=len(build.gap_edges),
        estimated_edges=estimated,
    )
