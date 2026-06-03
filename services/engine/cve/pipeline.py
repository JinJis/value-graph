"""[M3-ORCH-08] CVE orchestration (LangGraph).

Wire the cross-verification stages S0-S7 into one re-runnable, idempotent
pipeline over a theme:

    S0 ingest -> S1 extract -> S2 resolve -> S3 derive -> S4 reconcile
       -> S5 estimate (VSCA-est) -> S6 score -> S7 gap-detect

Each stage is a pure node function ``(state) -> {field: update}``; ``build_cve_graph``
binds the injected deps (Gemini router, resolver, ticket repo) into those nodes and
compiles a ``langgraph`` ``StateGraph``. ``run_cve`` runs the graph end-to-end and
persists the full intermediate ``CVEState`` via a :class:`CveRunRepository`.

Idempotency: every stage is deterministic in its inputs, and the ticket side
effects (conflict / estimate / gap tickets) are upserts keyed by (theme, target,
metric), so re-running with the same inputs yields the same state and does not
duplicate tickets.

Scope note: ingest takes already-uploaded documents + the companies' financials
and disclosure calendar as inputs (the real fetchers — market-data financials,
the M7 calendar — wire into this seam later). The reconciled edge metric is the
customer-side ``customer_cost_share`` (the worked CVE example's output side).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from services.engine.cve.derive import assign_cost_bucket, derive_trade
from services.engine.cve.estimate import estimate_edge
from services.engine.cve.extract import (
    ABSOLUTE,
    CUSTOMER_SHARE,
    SUPPLIER_SHARE,
    Claim,
    extract_claims,
)
from services.engine.cve.gaps import EdgeAssessment, GapSyncResult, sync_gaps
from services.engine.cve.reconcile import (
    Estimate,
    Reconciled,
    check_conservation,
    reconcile_and_ticket,
)
from services.engine.cve.resolve import Resolution, ResolutionStatus, Resolver, resolve_mentions
from services.engine.cve.run_repository import DONE, FAILED, CveRunRecord, CveRunRepository
from services.engine.cve.score import Scored, score_edge
from services.engine.llm.router import LLMRouter
from services.engine.tickets.repository import TicketRepository

# The canonical quantity we reconcile per edge (customer-side share of a cost bucket).
EDGE_METRIC = CUSTOMER_SHARE
# Cost bucket used when a share->cost conversion has no explicit bucket on the claim.
DEFAULT_COST_BUCKET = "COGS"


# --------------------------------------------------------------------------- state


class Document(BaseModel):
    """One ingested source document (already uploaded as a Source in Studio)."""

    source_id: str
    text: str
    as_of: str  # ISO date the document speaks to


class EdgeResult(BaseModel):
    """Per-edge accumulator threaded through S3-S7."""

    target: str  # "SUPPLIER->CUSTOMER"
    supplier: str
    customer: str
    as_of: str | None = None  # latest claim as-of for this edge
    estimates: list[Estimate] = Field(default_factory=list)  # customer_cost_share estimates
    reconciled: Reconciled | None = None
    estimated: bool = False  # filled by S5 VSCA-est (no disclosure)
    scored: Scored | None = None
    assessment: EdgeAssessment | None = None


class CVEState(BaseModel):
    """The full pipeline state — every intermediate, persisted at the end of a run."""

    theme_id: str
    trigger: str = "admin"
    today: str  # ISO date, passed in for deterministic freshness
    documents: list[Document] = Field(default_factory=list)
    # company -> {"revenue": x, "COGS": y, "CAPEX": ...}; enables the complementary side.
    financials: dict[str, dict[str, float]] = Field(default_factory=dict)
    calendar: dict[str, str] = Field(default_factory=dict)  # company -> next_expected_update ISO
    claims: list[Claim] = Field(default_factory=list)
    resolutions: list[Resolution] = Field(default_factory=list)
    edges: dict[str, EdgeResult] = Field(default_factory=dict)
    gap_results: list[GapSyncResult] = Field(default_factory=list)


class CVEResult(BaseModel):
    run_id: str | None
    status: str
    state: CVEState


# --------------------------------------------------------------------------- triggers

TRIGGERS = ("admin", "new_evidence", "scheduled")


# --------------------------------------------------------------------------- deps


class CVEDeps:
    """Injected collaborators; nodes are closures over an instance of this."""

    def __init__(
        self,
        *,
        router: LLMRouter,
        resolver: Resolver,
        ticket_repo: TicketRepository,
    ) -> None:
        self.router = router
        self.resolver = resolver
        self.ticket_repo = ticket_repo


# --------------------------------------------------------------------------- helpers


def _edge_key(supplier: str, customer: str) -> str:
    return f"{supplier}->{customer}"


def _bucket_value(funds: dict[str, float], bucket: str | None) -> float | None:
    if bucket is None:
        return None
    return funds.get(bucket)


def _claim_to_estimate(claim: Claim, financials: dict[str, dict[str, float]]) -> Estimate | None:
    """Convert one disclosure into a customer_cost_share estimate (the edge metric).

    Returns None when the complementary side can't be derived (missing financials)
    or the claim is qualitative — those become VSCA-est gaps in S5.
    """
    if claim.value is None:  # qualitative
        return None
    if claim.relation == CUSTOMER_SHARE:  # already the metric
        return Estimate(value=claim.value, source_id=claim.source_id)

    bucket = claim.cost_bucket or assign_cost_bucket(None) or DEFAULT_COST_BUCKET
    bucket_value = _bucket_value(financials.get(claim.object, {}), bucket)

    if claim.relation == SUPPLIER_SHARE:
        supplier_revenue = financials.get(claim.subject, {}).get("revenue")
        if supplier_revenue is None or bucket_value is None:
            return None
        derived = derive_trade(
            cost_bucket_hint=bucket,
            supplier_rev_share=claim.value,
            supplier_revenue=supplier_revenue,
            customer_cost_bucket_value=bucket_value,
        )
        if derived.customer_cost_share is None:
            return None
        return Estimate(value=derived.customer_cost_share, source_id=claim.source_id)

    if claim.relation == ABSOLUTE:
        if not bucket_value:
            return None
        return Estimate(value=100 * claim.value / bucket_value, source_id=claim.source_id)

    return None


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


# --------------------------------------------------------------------------- stages (S1-S7)


def s1_extract(state: CVEState, *, router: LLMRouter) -> dict[str, Any]:
    """S1: extract span-anchored claims from every ingested document."""
    claims: list[Claim] = []
    for doc in state.documents:
        claims.extend(
            extract_claims(doc.text, source_id=doc.source_id, as_of=doc.as_of, router=router)
        )
    return {"claims": claims}


def s2_resolve(
    state: CVEState, *, resolver: Resolver, ticket_repo: TicketRepository
) -> dict[str, Any]:
    """S2: resolve company mentions to canonical tickers (ticket the unresolved)."""
    mentions = sorted({c.subject for c in state.claims} | {c.object for c in state.claims})
    resolutions = resolve_mentions(
        mentions, resolver, theme_id=state.theme_id, ticket_repo=ticket_repo
    )
    canonical = {
        r.mention: r.ticker
        for r in resolutions
        if r.status is ResolutionStatus.RESOLVED and r.ticker is not None
    }
    # Canonicalize claim endpoints so edges group consistently; keep originals if unresolved.
    resolved_claims = [
        c.model_copy(
            update={
                "subject": canonical.get(c.subject, c.subject),
                "object": canonical.get(c.object, c.object),
            }
        )
        for c in state.claims
    ]
    return {"resolutions": resolutions, "claims": resolved_claims}


def s3_derive(state: CVEState) -> dict[str, Any]:
    """S3: group claims into edges; derive the customer-side metric for each disclosure."""
    edges: dict[str, EdgeResult] = {}
    for claim in state.claims:
        key = _edge_key(claim.subject, claim.object)
        edge = edges.get(key)
        if edge is None:
            edge = EdgeResult(target=key, supplier=claim.subject, customer=claim.object)
            edges[key] = edge
        if edge.as_of is None or claim.as_of > edge.as_of:
            edge.as_of = claim.as_of
        estimate = _claim_to_estimate(claim, state.financials)
        if estimate is not None:
            edge.estimates.append(estimate)
    return {"edges": edges}


def s4_reconcile(state: CVEState, *, ticket_repo: TicketRepository) -> dict[str, Any]:
    """S4: reconcile each edge's estimates (flag conflicts, never average)."""
    edges = {k: v.model_copy(deep=True) for k, v in state.edges.items()}
    for edge in edges.values():
        if not edge.estimates:
            continue
        edge.reconciled = reconcile_and_ticket(
            edge.estimates,
            edge_target=edge.target,
            metric=EDGE_METRIC,
            theme_id=state.theme_id,
            ticket_repo=ticket_repo,
        )
    return {"edges": edges}


def s5_estimate(
    state: CVEState, *, router: LLMRouter, ticket_repo: TicketRepository
) -> dict[str, Any]:
    """S5: VSCA-est for edges with no derivable disclosure (always estimated + ticket)."""
    edges = {k: v.model_copy(deep=True) for k, v in state.edges.items()}
    for edge in edges.values():
        if edge.reconciled is not None or edge.estimates:
            continue
        estimate = estimate_edge(
            supplier=edge.supplier,
            customer=edge.customer,
            metric=EDGE_METRIC,
            router=router,
            theme_id=state.theme_id,
            ticket_repo=ticket_repo,
        )
        edge.estimated = True
        edge.reconciled = Reconciled(
            point=estimate.point,
            interval=estimate.interval,
            status="reconciled",
            n_sources=0,
            sources=[],
        )
    return {"edges": edges}


def s6_score(state: CVEState) -> dict[str, Any]:
    """S6: score each edge — confidence tier + interval + freshness + next-update."""
    today = _parse_date(state.today) or date.today()
    edges = {k: v.model_copy(deep=True) for k, v in state.edges.items()}
    for edge in edges.values():
        if edge.reconciled is None:
            continue
        next_update = state.calendar.get(edge.supplier) or state.calendar.get(edge.customer)
        edge.scored = score_edge(
            interval=edge.reconciled.interval,
            n_independent_sources=edge.reconciled.n_sources,
            estimated=edge.estimated,
            as_of=_parse_date(edge.as_of),
            next_expected_update=_parse_date(next_update),
            today=today,
        )
    return {"edges": edges}


def s7_gaps(state: CVEState, *, ticket_repo: TicketRepository) -> dict[str, Any]:
    """S7: assess each edge and sync gap tickets (estimated/conflict/stale/conservation)."""
    # Per-supplier conservation: Σ of a supplier's disclosed revenue shares <= 100%.
    supplier_shares: dict[str, list[float]] = {}
    for claim in state.claims:
        if claim.relation == SUPPLIER_SHARE and claim.value is not None:
            supplier_shares.setdefault(claim.subject, []).append(claim.value)
    conservation_ok = {
        supplier: check_conservation(shares).ok for supplier, shares in supplier_shares.items()
    }

    edges = {k: v.model_copy(deep=True) for k, v in state.edges.items()}
    gap_results: list[GapSyncResult] = []
    for edge in edges.values():
        if edge.scored is None or edge.reconciled is None:
            continue
        assessment = EdgeAssessment(
            edge_target=edge.target,
            confidence=edge.scored.confidence,
            status=edge.reconciled.status,
            freshness=edge.scored.freshness,
            conservation_ok=conservation_ok.get(edge.supplier, True),
        )
        edge.assessment = assessment
        gap_results.append(
            sync_gaps(assessment, theme_id=state.theme_id, ticket_repo=ticket_repo)
        )
    return {"edges": edges, "gap_results": gap_results}


# --------------------------------------------------------------------------- graph


def build_cve_graph(deps: CVEDeps) -> Any:
    """Compile the S1-S7 LangGraph, binding injected deps into each node."""
    graph = StateGraph(CVEState)

    graph.add_node("S1_extract", lambda s: s1_extract(s, router=deps.router))
    graph.add_node(
        "S2_resolve",
        lambda s: s2_resolve(s, resolver=deps.resolver, ticket_repo=deps.ticket_repo),
    )
    graph.add_node("S3_derive", s3_derive)
    graph.add_node("S4_reconcile", lambda s: s4_reconcile(s, ticket_repo=deps.ticket_repo))
    graph.add_node(
        "S5_estimate",
        lambda s: s5_estimate(s, router=deps.router, ticket_repo=deps.ticket_repo),
    )
    graph.add_node("S6_score", s6_score)
    graph.add_node("S7_gaps", lambda s: s7_gaps(s, ticket_repo=deps.ticket_repo))

    graph.add_edge(START, "S1_extract")
    graph.add_edge("S1_extract", "S2_resolve")
    graph.add_edge("S2_resolve", "S3_derive")
    graph.add_edge("S3_derive", "S4_reconcile")
    graph.add_edge("S4_reconcile", "S5_estimate")
    graph.add_edge("S5_estimate", "S6_score")
    graph.add_edge("S6_score", "S7_gaps")
    graph.add_edge("S7_gaps", END)

    return graph.compile()


# --------------------------------------------------------------------------- entry point


def run_cve(
    *,
    theme_id: str,
    deps: CVEDeps,
    documents: list[Document] | None = None,
    financials: dict[str, dict[str, float]] | None = None,
    calendar: dict[str, str] | None = None,
    today: str,
    trigger: str = "admin",
    run_repo: CveRunRepository | None = None,
    graph: Callable[[Any], dict[str, Any]] | None = None,
) -> CVEResult:
    """Run the full S0-S7 CVE pipeline for a theme and persist the run.

    ``trigger`` is one of :data:`TRIGGERS` (admin / new_evidence / scheduled). When
    ``run_repo`` is supplied the run (and its full intermediate state) is persisted,
    moving RUNNING -> DONE / FAILED.
    """
    if trigger not in TRIGGERS:
        raise ValueError(f"unknown trigger {trigger!r}; expected one of {TRIGGERS}")

    initial = CVEState(
        theme_id=theme_id,
        trigger=trigger,
        today=today,
        documents=documents or [],
        financials=financials or {},
        calendar=calendar or {},
    )

    record: CveRunRecord | None = run_repo.start(theme_id, trigger) if run_repo else None
    run_id = record.id if record else None

    compiled = build_cve_graph(deps) if graph is None else None
    try:
        raw = (graph or compiled.invoke)(initial)  # type: ignore[union-attr]
        final = CVEState.model_validate(raw)
    except Exception:
        if run_repo and run_id:
            run_repo.finish(run_id, status=FAILED, state=initial.model_dump(mode="json"))
        raise

    if run_repo and run_id:
        run_repo.finish(run_id, status=DONE, state=final.model_dump(mode="json"))

    return CVEResult(run_id=run_id, status=DONE, state=final)
