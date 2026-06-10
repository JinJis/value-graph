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

import io
import logging
from collections.abc import Generator, Iterator, Sequence
from datetime import date
from typing import Any

from pydantic import BaseModel

from services.engine.blueprint.models import BlueprintRecord
from services.engine.calendar.repository import CalendarRepository, next_update_map
from services.engine.cve.chain_research import research_chain_events
from services.engine.cve.cost_bucket import LLMCostBucketClassifier
from services.engine.cve.extract import Claim
from services.engine.cve.pipeline import (
    TRIGGERS,
    CVEDeps,
    CVEState,
    Document,
    ResearchMeta,
    stream_cve_state,
)
from services.engine.cve.resolve import CanonicalCompany, LLMAdjudicator, Resolver
from services.engine.cve.run_repository import DONE, FAILED, CveRunRepository
from services.engine.db.graph_store import GraphStore
from services.engine.db.persist import persist_cve_run
from services.engine.financials.repository import FinancialsRepository, financials_map
from services.engine.llm.router import LLMRouter
from services.engine.storage import Storage
from services.engine.themes.models import SourceRecord, Theme
from services.engine.themes.repository import ThemeRepository
from services.engine.tickets.policy import close_superseded_tickets
from services.engine.tickets.repository import TicketRepository

# Financial buckets the CVE derivation needs (supplier revenue + customer COGS); missing
# ones become tickets so "couldn't source -> ticket" holds for financials too.
_REQUIRED_FINANCIAL_BUCKETS = ("revenue", "cogs")

logger = logging.getLogger("valuegraph.engine.cve.run")

Event = dict[str, Any]

# Human-readable label per pipeline stage, for the live progress timeline.
_STAGE_LABELS = {
    "S1_extract": "extract claims",
    "S2_resolve": "resolve entities",
    "S3_derive": "derive edges",
    "S4_reconcile": "reconcile",
    "S5_estimate": "estimate gaps (VSCA)",
    "S6_score": "score",
    "S7_gaps": "gap-detect",
}


def _stage_detail(stage: str, state: CVEState) -> str:
    """One-line summary of what a stage produced, for the progress timeline."""
    edges = state.edges.values()
    if stage == "S1_extract":
        return f"{len(state.claims)} claim(s)"
    if stage == "S2_resolve":
        return f"{len(state.resolutions)} mention(s) resolved"
    if stage == "S3_derive":
        return f"{len(state.edges)} edge(s)"
    if stage == "S4_reconcile":
        return f"{sum(1 for e in edges if e.reconciled is not None)} reconciled"
    if stage == "S5_estimate":
        return f"{sum(1 for e in edges if e.estimated)} estimated"
    if stage == "S6_score":
        return f"{sum(1 for e in edges if e.scored is not None)} scored"
    if stage == "S7_gaps":
        return f"{len(state.gap_results)} edge(s) assessed"
    return ""


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


def _pdf_text(raw: bytes) -> str:
    """Extract a PDF's text layer (best effort). Returns "" for a scanned/image-only PDF
    (no text layer) or an unparsable file — the caller then skips it."""
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - dependency is declared, guard for safety
        logger.warning("cve.ingest pdf skipped: pypdf not installed")
        return ""
    try:
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception as exc:  # corrupt/encrypted PDF — skip, don't fail the run
        logger.warning("cve.ingest pdf parse failed: %s", exc)
        return ""


def _source_text(raw: bytes, source: SourceRecord) -> str:
    """Decode an uploaded file Source to text. PDFs go through the PDF text extractor;
    everything else is treated as UTF-8 text."""
    content_type = (source.content_type or "").lower()
    filename = (source.original_filename or "").lower()
    is_pdf = (
        content_type.startswith("application/pdf")
        or filename.endswith(".pdf")
        or raw[:5] == b"%PDF-"
    )
    if is_pdf:
        return _pdf_text(raw)
    return raw.decode("utf-8", "ignore").strip()


def _documents(
    sources: list[SourceRecord], storage: Storage, *, fallback_as_of: str
) -> list[Document]:
    """Decode each uploaded file Source into a CVE :class:`Document` (best effort). Handles
    UTF-8 text and PDFs; URL-only citations and unreadable/empty files are skipped."""
    docs: list[Document] = []
    for source in sources:
        if not source.storage_key:
            continue  # URL-only citation: no stored text to extract from
        try:
            raw = storage.load(source.storage_key)
        except Exception as exc:  # missing/unreadable blob — skip, don't fail the run
            logger.warning("cve.ingest skip source=%s: %s", source.id, exc)
            continue
        text = _source_text(raw, source)
        if not text:
            logger.warning(
                "cve.ingest no-text source=%s type=%s file=%s — skipped",
                source.id,
                source.content_type,
                source.original_filename,
            )
            continue
        as_of = source.as_of_date.isoformat() if source.as_of_date else fallback_as_of
        docs.append(Document(source_id=source.id, text=text, as_of=as_of))
    return docs


def run_cve_events_for_theme(
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
    financials_repo: FinancialsRepository | None = None,
    seed_claims: Sequence[Claim] = (),
    research: ResearchMeta | None = None,
    theme_name: str = "",
    today: str | None = None,
    trigger: str = "admin",
) -> Iterator[Event]:
    """Run S1-S7 for ``theme_id``, streaming per-stage progress and persisting the build.

    Emits: ``start`` (inputs) → one ``stage`` per S1-S7 (with a count) → ``persisted``
    (the build summary) → ``done``; any failure marks the run FAILED and emits ``error``.
    The full run + persistence happen as a side effect of consuming this generator.
    """
    if trigger not in TRIGGERS:
        raise ValueError(f"unknown trigger {trigger!r}; expected one of {TRIGGERS}")
    today = today or date.today().isoformat()
    documents = _documents(sources, storage, fallback_as_of=today)
    companies = [
        CanonicalCompany(ticker=c.ticker, name=c.name) for c in blueprint.companies
    ]
    resolver = Resolver(companies=companies, adjudicator=LLMAdjudicator(router=router))
    # Theme-aware cost-bucket typing so the engine isn't hardwired to one domain.
    classifier = LLMCostBucketClassifier(router, theme=theme_name or theme_id)
    deps = CVEDeps(
        router=router,
        resolver=resolver,
        ticket_repo=ticket_repo,
        cost_bucket_classifier=classifier,
    )
    products = {c.ticker: c.products for c in blueprint.companies}
    tickers = [c.ticker for c in blueprint.companies]
    calendar = next_update_map(calendar_repo, tickers) if calendar_repo is not None else {}
    financials = financials_map(financials_repo, tickers) if financials_repo is not None else {}

    logger.info(
        "cve.run theme=%s documents=%d companies=%d calendar=%d financials=%d trigger=%s",
        theme_id,
        len(documents),
        len(companies),
        len(calendar),
        len(financials),
        trigger,
    )
    yield {
        "event": "start",
        "documents": len(documents),
        "companies": len(companies),
        "calendar": len(calendar),
        "financials": len(financials),
    }

    # Retire any page-backed tickets (financials/calendar) left over from before those flows
    # moved to their own Studio step — they're filled there now, not via tickets.
    retired = close_superseded_tickets(theme_id, ticket_repo)
    if retired:
        logger.info("cve.run.retired_page_backed_tickets theme=%s count=%d", theme_id, retired)
        yield {"event": "tickets_retired", "count": retired}

    initial = CVEState(
        theme_id=theme_id,
        trigger=trigger,
        research=research,
        today=today,
        documents=documents,
        financials=financials,  # complementary side -> derived (not just estimated) edges
        calendar=calendar,
        products=products,  # ticker -> products, for theme-aware cost-bucket typing
        claims=list(seed_claims),  # researched trades seeded before S1 (merged, not replaced)
    )
    record = run_repo.start(theme_id, trigger)
    state = initial
    try:
        for stage, state in stream_cve_state(initial, deps):
            detail = _stage_detail(stage, state)
            logger.info("cve.stage theme=%s %s %s", theme_id, stage, detail)
            yield {
                "event": "stage",
                "stage": stage,
                "label": _STAGE_LABELS.get(stage, stage),
                "detail": detail,
            }
    except Exception as exc:
        run_repo.finish(record.id, status=FAILED, state=initial.model_dump(mode="json"))
        logger.warning("cve.failed theme=%s: %s", theme_id, exc)
        yield {"event": "error", "detail": f"{type(exc).__name__}: {exc}"}
        return

    run_repo.finish(record.id, status=DONE, state=state.model_dump(mode="json"))
    build = persist_cve_run(state, graph_store)
    estimated = sum(1 for e in state.edges.values() if e.estimated)
    logger.info(
        "cve.persisted theme=%s build=%s edges=%d publishable=%d ghost=%d claims=%d",
        theme_id,
        build.version,
        len(state.edges),
        len(build.edges),
        len(build.gap_edges),
        len(state.claims),
    )
    yield {
        "event": "persisted",
        "run_id": record.id,
        "status": DONE,
        "build_version": build.version,
        "documents_ingested": len(documents),
        "claims": len(state.claims),
        "edges": len(state.edges),
        "publishable_edges": len(build.edges),
        "ghost_edges": len(build.gap_edges),
        "estimated_edges": estimated,
    }
    yield {"event": "done"}


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
    financials_repo: FinancialsRepository | None = None,
    seed_claims: Sequence[Claim] = (),
    theme_name: str = "",
    today: str | None = None,
    trigger: str = "admin",
) -> CveRunSummary:
    """Non-streaming run: drive :func:`run_cve_events_for_theme` to completion and
    return its summary (same persistence + side effects)."""
    summary: Event | None = None
    for event in run_cve_events_for_theme(
        theme_id=theme_id,
        blueprint=blueprint,
        sources=sources,
        storage=storage,
        router=router,
        ticket_repo=ticket_repo,
        graph_store=graph_store,
        run_repo=run_repo,
        calendar_repo=calendar_repo,
        financials_repo=financials_repo,
        seed_claims=seed_claims,
        theme_name=theme_name,
        today=today,
        trigger=trigger,
    ):
        if event["event"] == "error":
            raise RuntimeError(str(event["detail"]))
        if event["event"] == "persisted":
            summary = event
    if summary is None:  # pragma: no cover - persisted always precedes done
        raise RuntimeError("CVE run produced no result")
    return CveRunSummary(
        run_id=summary["run_id"],
        status=summary["status"],
        build_version=summary["build_version"],
        documents_ingested=summary["documents_ingested"],
        claims=summary["claims"],
        edges=summary["edges"],
        publishable_edges=summary["publishable_edges"],
        ghost_edges=summary["ghost_edges"],
        estimated_edges=summary["estimated_edges"],
    )


def _missing_financials(
    blueprint: BlueprintRecord, financials_repo: FinancialsRepository
) -> list[dict[str, Any]]:
    """Companies still missing a required bucket (revenue/COGS). Financials are admin-entered
    (or filled on the Financials step's Deep Research) — NOT a Deep-Research ticket — so we
    surface them as guidance to fill on the Financials step rather than opening tickets."""
    tickers = [c.ticker for c in blueprint.companies]
    have = {r.company_ticker: r for r in financials_repo.list_for(tickers)}
    out: list[dict[str, Any]] = []
    for company in blueprint.companies:
        record = have.get(company.ticker)
        missing = [
            b
            for b in _REQUIRED_FINANCIAL_BUCKETS
            if record is None or getattr(record, b) is None
        ]
        if missing:
            out.append(
                {"ticker": company.ticker, "name": company.name, "missing": missing}
            )
    return out


def _drive_research(
    gen: Iterator[Event],
) -> Generator[Event, None, tuple[list[Claim], str | None]]:
    """Re-yield every event from a research stream and return ``(claims, error)``: the
    streamed claims (its return value) plus the detail of any ``error`` event it emitted."""
    error: str | None = None
    while True:
        try:
            event = next(gen)
        except StopIteration as stop:
            claims: list[Claim] = stop.value or []
            return claims, error
        if event.get("event") == "error":
            error = str(event.get("detail"))
        yield event


def research_and_build_events(
    *,
    theme: Theme,
    blueprint: BlueprintRecord,
    sources: list[SourceRecord],
    storage: Storage,
    router: LLMRouter,
    ticket_repo: TicketRepository,
    theme_repo: ThemeRepository,
    graph_store: GraphStore,
    run_repo: CveRunRepository,
    calendar_repo: CalendarRepository | None = None,
    financials_repo: FinancialsRepository | None = None,
    today: str | None = None,
    trigger: str = "admin",
) -> Iterator[Event]:
    """One streamed action: Deep Research the chain into claims + financials, then run the
    CVE pipeline seeded with those claims, and ticket the financials it couldn't source."""
    today = today or date.today().isoformat()

    yield {"event": "phase", "phase": "research"}
    claims: list[Claim] = []
    research: ResearchMeta | None = None
    if financials_repo is not None:
        # Drive the research stream, re-yielding every event but capturing any error detail
        # (e.g. a bad GOOGLE_API_KEY) so diagnostics can explain a 0-trade build.
        claims, research_error = yield from _drive_research(
            research_chain_events(
                theme, blueprint, theme_repo, financials_repo, router, today=today
            )
        )
        research = ResearchMeta(
            ran=True, trades_found=len(claims), error=research_error
        )
        # Missing financials are filled on the Financials step (manual or per-company Deep
        # Research), not via tickets — surface them as guidance instead of opening tickets.
        missing = _missing_financials(blueprint, financials_repo)
        if missing:
            yield {"event": "financials_missing", "count": len(missing), "companies": missing}

    yield {"event": "phase", "phase": "build"}
    yield from run_cve_events_for_theme(
        theme_id=theme.id,
        blueprint=blueprint,
        sources=sources,
        storage=storage,
        router=router,
        ticket_repo=ticket_repo,
        graph_store=graph_store,
        run_repo=run_repo,
        calendar_repo=calendar_repo,
        financials_repo=financials_repo,
        seed_claims=claims,
        research=research,
        theme_name=theme.name,
        today=today,
        trigger=trigger,
    )
