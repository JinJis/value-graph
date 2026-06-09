"""Build diagnostics — explain WHY a theme's CVE build is empty (or what's missing).

The Studio admin keeps hitting "graph not assembled (incomplete)" with 0 relationships and
no clue why. This aggregates every input/output signal of the build pipeline into one
read-only report so the admin can see, concretely: what data exists (blueprint, source
documents, financials, calendar), what the last CVE run produced at EACH stage (claims →
edges → reconciled → estimated → scored → gaps), and a plain-language list of findings with
the next action to take. Pure read — no mutation, no LLM calls.

A figure can only reach the publishable graph if its edge has BOTH ``reconciled`` and
``scored`` set (see :func:`services.engine.db.artifacts.build_from_cve`), so an empty graph
almost always traces to an earlier stage going to zero — that's what this surfaces.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from services.engine.blueprint.models import BlueprintRecord
from services.engine.calendar.repository import CalendarRepository, next_update_map
from services.engine.cve.run_repository import (
    DONE,
    FAILED,
    RUNNING,
    CveRunRecord,
    CveRunRepository,
)
from services.engine.cve.run_service import _REQUIRED_FINANCIAL_BUCKETS
from services.engine.db.graph_store import GraphStore
from services.engine.financials.repository import FinancialsRepository
from services.engine.publish.assemble import DEFAULT_COMPLETENESS_THRESHOLD
from services.engine.themes.models import SourceRecord


class StageCounts(BaseModel):
    """What one run produced at each S1-S7 stage (read from its persisted state)."""

    documents: int = 0
    claims: int = 0
    resolutions: int = 0
    edges: int = 0
    reconciled: int = 0
    estimated: int = 0
    scored: int = 0
    gap_results: int = 0


class RunInfo(BaseModel):
    id: str
    status: str
    trigger: str
    created_at: datetime
    stages: StageCounts | None = None


class SourcesInfo(BaseModel):
    total: int = 0
    documents: int = 0  # uploaded files (have stored bytes -> feed S1 extraction)
    citations: int = 0  # URL-only (no stored text -> NOT ingested as documents)


class MissingFinancials(BaseModel):
    ticker: str
    name: str
    missing: list[str] = Field(default_factory=list)  # required buckets still absent


class FinancialsInfo(BaseModel):
    required: list[str] = Field(default_factory=list)
    covered: int = 0
    total: int = 0
    missing: list[MissingFinancials] = Field(default_factory=list)


class BuildInfo(BaseModel):
    version: int | None = None
    publishable_edges: int = 0
    gap_edges: int = 0
    total_edges: int = 0
    completeness: float = 0.0
    threshold: float = DEFAULT_COMPLETENESS_THRESHOLD
    meets_threshold: bool = False


class Finding(BaseModel):
    """One plain-language diagnosis line + what to do about it."""

    level: str  # "error" | "warn" | "ok"
    code: str
    message: str
    action: str | None = None


class BuildDiagnostics(BaseModel):
    theme_id: str
    has_blueprint: bool
    blueprint_companies: int
    sources: SourcesInfo
    financials: FinancialsInfo
    calendar_covered: int
    last_run: RunInfo | None
    runs: list[RunInfo] = Field(default_factory=list)
    build: BuildInfo
    findings: list[Finding] = Field(default_factory=list)


def _stage_counts(state: dict[str, Any]) -> StageCounts:
    """Derive per-stage counts from a persisted CVEState dump (best effort)."""
    edges = state.get("edges") or {}
    edge_vals = list(edges.values()) if isinstance(edges, dict) else []
    return StageCounts(
        documents=len(state.get("documents") or []),
        claims=len(state.get("claims") or []),
        resolutions=len(state.get("resolutions") or []),
        edges=len(edge_vals),
        reconciled=sum(1 for e in edge_vals if e.get("reconciled") is not None),
        estimated=sum(1 for e in edge_vals if e.get("estimated")),
        scored=sum(1 for e in edge_vals if e.get("scored") is not None),
        gap_results=len(state.get("gap_results") or []),
    )


def _run_info(record: CveRunRecord) -> RunInfo:
    stages = _stage_counts(record.state) if record.state else None
    return RunInfo(
        id=record.id,
        status=record.status,
        trigger=record.trigger,
        created_at=record.created_at,
        stages=stages,
    )


def _sources_info(sources: list[SourceRecord]) -> SourcesInfo:
    documents = sum(1 for s in sources if s.storage_key)
    return SourcesInfo(
        total=len(sources),
        documents=documents,
        citations=len(sources) - documents,
    )


def _financials_info(
    blueprint: BlueprintRecord | None, financials_repo: FinancialsRepository
) -> FinancialsInfo:
    required = list(_REQUIRED_FINANCIAL_BUCKETS)
    if blueprint is None:
        return FinancialsInfo(required=required)
    tickers = [c.ticker for c in blueprint.companies]
    records = {r.company_ticker: r for r in financials_repo.list_for(tickers)}
    missing: list[MissingFinancials] = []
    for company in blueprint.companies:
        record = records.get(company.ticker)
        gaps = [b for b in required if record is None or getattr(record, b) is None]
        if gaps:
            missing.append(
                MissingFinancials(ticker=company.ticker, name=company.name, missing=gaps)
            )
    return FinancialsInfo(
        required=required,
        covered=len(blueprint.companies) - len(missing),
        total=len(blueprint.companies),
        missing=missing,
    )


def _build_info(graph_store: GraphStore, theme_id: str, threshold: float) -> BuildInfo:
    build = graph_store.load_latest(theme_id)
    if build is None:
        return BuildInfo(threshold=threshold)
    publishable = len(build.edges)
    gaps = len(build.gap_edges)
    total = publishable + gaps
    return BuildInfo(
        version=build.version,
        publishable_edges=publishable,
        gap_edges=gaps,
        total_edges=total,
        completeness=(publishable / total) if total else 0.0,
        threshold=threshold,
        meets_threshold=total > 0 and (publishable / total) >= threshold,
    )


def _findings(
    *,
    has_blueprint: bool,
    blueprint_companies: int,
    sources: SourcesInfo,
    financials: FinancialsInfo,
    calendar_covered: int,
    last_run: RunInfo | None,
    build: BuildInfo,
) -> list[Finding]:
    """Turn the raw signals into an ordered, plain-language diagnosis."""
    out: list[Finding] = []

    if not has_blueprint:
        out.append(
            Finding(
                level="error",
                code="no_blueprint",
                message="No blueprint — there are no companies to build a graph from.",
                action="Generate a blueprint on the Blueprint step first.",
            )
        )
        return out  # everything downstream depends on the blueprint
    if blueprint_companies < 2:
        out.append(
            Finding(
                level="warn",
                code="few_companies",
                message=f"Only {blueprint_companies} company in the blueprint — a supply "
                "chain needs at least two (a supplier and a customer).",
                action="Refine/discover more companies on the Blueprint step.",
            )
        )

    # Input availability.
    if sources.documents == 0:
        out.append(
            Finding(
                level="warn",
                code="no_documents",
                message="No uploaded source documents — CVE extraction (S1) has nothing to "
                f"read ({sources.citations} URL-only citation(s) carry no stored text).",
                action="Use 'Research & build' (Deep Research seeds trades) or upload "
                "filings on the Sources step.",
            )
        )
    if financials.total and financials.missing:
        out.append(
            Finding(
                level="warn",
                code="missing_financials",
                message=f"Financials ({'/'.join(financials.required)}) missing for "
                f"{len(financials.missing)}/{financials.total} companies — without the "
                "complementary side, disclosures stay estimated (or become gaps), not derived.",
                action="Auto-fill on the Financials step, then re-run the build.",
            )
        )

    # Run / pipeline outcome.
    if last_run is None:
        out.append(
            Finding(
                level="error",
                code="no_run",
                message="No CVE run has completed for this theme yet — the graph is empty "
                "because nothing has been built.",
                action="Click 'Research & build' (or 'Run CVE only') on this step.",
            )
        )
    else:
        s = last_run.stages
        if last_run.status == FAILED:
            out.append(
                Finding(
                    level="error",
                    code="run_failed",
                    message="The last CVE run FAILED before finishing — likely an LLM/API "
                    "error (check GOOGLE_API_KEY and server logs).",
                    action="Fix the error and re-run.",
                )
            )
        elif last_run.status == RUNNING:
            out.append(
                Finding(
                    level="warn",
                    code="run_running",
                    message="A CVE run is still in progress — counts below may be partial.",
                    action="Wait for it to finish, then re-check.",
                )
            )
        elif s is not None and last_run.status == DONE:
            if s.claims == 0:
                out.append(
                    Finding(
                        level="error",
                        code="no_claims",
                        message="The last run extracted 0 claims — Deep Research returned no "
                        "usable trades and no documents were ingested, so no edges can form.",
                        action="Run 'Research & build' with a valid GOOGLE_API_KEY, or upload "
                        "filings that disclose supplier→customer trades.",
                    )
                )
            elif s.edges == 0:
                out.append(
                    Finding(
                        level="warn",
                        code="no_edges",
                        message=f"{s.claims} claim(s) found but 0 edges derived — the claims "
                        "were qualitative (no number) or entity resolution didn't map them to "
                        "blueprint tickers.",
                        action="Check that trades reference known tickers; add quantified "
                        "disclosures.",
                    )
                )
            elif s.scored == 0:
                out.append(
                    Finding(
                        level="warn",
                        code="no_scored",
                        message=f"{s.edges} edge(s) derived but 0 were scored/reconciled — they "
                        "won't reach the publishable graph (missing provenance or financials).",
                        action="Fill financials + ensure each trade carries a Source, then "
                        "re-run.",
                    )
                )

    # Why are edges landing as GAPS instead of publishable? A SuppliesEdge MUST carry both
    # as_of_date AND next_expected_update (graph-schema required fields); missing either
    # demotes the edge to a drawn gap. The two usual culprits — an empty Disclosure Calendar
    # (no next_expected_update for ANY edge) and estimated edges (no source claim -> no
    # as_of_date) — explain a build that has edges yet 0% publishable.
    if build.total_edges > 0 and build.publishable_edges < build.total_edges:
        if calendar_covered == 0:
            out.append(
                Finding(
                    # The blocker when nothing is publishable; otherwise a contributing warning.
                    level="error" if build.publishable_edges == 0 else "warn",
                    code="calendar_empty",
                    message="The Disclosure Calendar has 0 entries for this theme's companies, "
                    "so every edge is missing 'next_expected_update' — a required field — and is "
                    f"demoted to a drawn gap ({build.gap_edges}/{build.total_edges} edges). This "
                    "is the main reason the build is "
                    f"{round(build.completeness * 100)}% publishable.",
                    action="Add per-company filing dates on the Disclosure Calendar step, then "
                    "re-run the build (or re-assemble).",
                )
            )
        estimated = last_run.stages.estimated if last_run and last_run.stages else 0
        if estimated:
            out.append(
                Finding(
                    level="warn",
                    code="estimated_no_asof",
                    message=f"{estimated} edge(s) are algorithmic estimates (VSCA-est) with no "
                    "backing disclosure, so they carry no 'as_of_date' and stay gaps by design — "
                    "estimates are drawn as ghosts, never published as fact.",
                    action="Fill the missing disclosures (tickets / 'Research & build') to turn "
                    "estimates into derived, dated edges.",
                )
            )
        if calendar_covered > 0 and not estimated and build.publishable_edges == 0:
            out.append(
                Finding(
                    level="warn",
                    code="edges_missing_provenance",
                    message="Every edge was demoted to a gap even though the Disclosure Calendar "
                    "has entries — the edges are missing a required figure date (as_of_date or "
                    "next_expected_update) or another SuppliesEdge field.",
                    action="Open an edge in the Build/Sources review to see which figure lacks a "
                    "dated Source, fill it, then re-run.",
                )
            )

    # Final graph state.
    if build.total_edges == 0:
        out.append(
            Finding(
                level="error",
                code="empty_graph",
                message="The latest build has 0 publishable and 0 gap edges — there is "
                "nothing to assemble or publish (completeness needs at least one relationship).",
                action="Resolve the issues above, then re-run the build.",
            )
        )
    elif not build.meets_threshold:
        out.append(
            Finding(
                level="warn",
                code="below_threshold",
                message=f"Build is {round(build.completeness * 100)}% complete "
                f"({build.publishable_edges}/{build.total_edges}), below the "
                f"{round(build.threshold * 100)}% threshold.",
                action="Improve coverage, or publish with a logged override.",
            )
        )
    else:
        out.append(
            Finding(
                level="ok",
                code="ready",
                message=f"Build looks healthy: {build.publishable_edges} publishable / "
                f"{build.total_edges} relationships.",
                action=None,
            )
        )
    return out


def build_diagnostics(
    *,
    theme_id: str,
    blueprint: BlueprintRecord | None,
    sources: list[SourceRecord],
    financials_repo: FinancialsRepository,
    calendar_repo: CalendarRepository | None,
    run_repo: CveRunRepository,
    graph_store: GraphStore,
    threshold: float = DEFAULT_COMPLETENESS_THRESHOLD,
    run_history: int = 10,
) -> BuildDiagnostics:
    """Aggregate every build signal for a theme into one diagnostic report."""
    companies = blueprint.companies if blueprint is not None else []
    sources_info = _sources_info(sources)
    financials_info = _financials_info(blueprint, financials_repo)

    tickers = [c.ticker for c in companies]
    calendar = (
        next_update_map(calendar_repo, tickers) if calendar_repo is not None else {}
    )

    runs = [_run_info(r) for r in run_repo.list_runs(theme_id, limit=run_history)]
    last_run = runs[0] if runs else None
    build = _build_info(graph_store, theme_id, threshold)

    findings = _findings(
        has_blueprint=blueprint is not None,
        blueprint_companies=len(companies),
        sources=sources_info,
        financials=financials_info,
        calendar_covered=len(calendar),
        last_run=last_run,
        build=build,
    )

    return BuildDiagnostics(
        theme_id=theme_id,
        has_blueprint=blueprint is not None,
        blueprint_companies=len(companies),
        sources=sources_info,
        financials=financials_info,
        calendar_covered=len(calendar),
        last_run=last_run,
        runs=runs,
        build=build,
        findings=findings,
    )
