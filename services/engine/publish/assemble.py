"""[M4-ASM-02] Graph assembly — turn a persisted ThemeBuild into a publishable graph.

**Best-effort assembly.** We always surface the graph we have: nodes + the edges that meet
the SuppliesEdge schema rules (admitted as fully-provenanced figures), plus every gap edge
carried as a drawn "ghost" edge (they expose no figure, so they don't violate the validation
gate). Completeness is REPORTED for transparency but never withholds the graph — "gaps are
drawn, not hidden" (CLAUDE.md §2). Refusing to publish because one figure is missing would
hide the whole chain; instead we publish what's verified now and let the admin fill the gaps
later (re-run + re-publish a new version). The only thing that blocks publish is an *admitted*
figure missing provenance — the validation gate (M4-GATE-03), not low completeness.

Completeness here = quantified relationships / all discovered relationships
(publishable edges / (publishable + gap edges)) — a quality signal shown to the admin and the
Terminal, not a gate. A truly empty build (no publishable AND no gap edges) has nothing to
show, so it stays unassembled. Publish to Production is M4-PUB-04.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from graph_schema import is_valid
from services.engine.db.artifacts import GapEdge, ThemeBuild

logger = logging.getLogger(__name__)

# Default share of discovered relationships that must be quantified to assemble.
DEFAULT_COMPLETENESS_THRESHOLD = 0.7


class OverrideLog(BaseModel):
    """An admin's explicit decision to assemble below threshold (audited)."""

    actor: str
    reason: str


class CompletenessReport(BaseModel):
    publishable_edges: int
    gap_edges: int
    total_edges: int
    completeness: float
    threshold: float
    meets_threshold: bool


class AssembledGraph(BaseModel):
    """The publishable graph (or a withheld result explaining why)."""

    theme_id: str
    version: int
    assembled: bool
    completeness: CompletenessReport
    override: OverrideLog | None = None
    companies: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)  # publishable SuppliesEdges only
    ghost_edges: list[GapEdge] = Field(default_factory=list)
    # "supplier->customer" -> backing Source refs, for per-figure provenance (PROV-02).
    edge_sources: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    # "supplier->customer" -> {reconciliation, claims} for the edge inspector (EDGE-03).
    edge_details: dict[str, dict[str, Any]] = Field(default_factory=dict)


def _completeness(publishable: int, gaps: int, threshold: float) -> CompletenessReport:
    total = publishable + gaps
    ratio = publishable / total if total else 0.0
    return CompletenessReport(
        publishable_edges=publishable,
        gap_edges=gaps,
        total_edges=total,
        completeness=ratio,
        threshold=threshold,
        meets_threshold=total > 0 and ratio >= threshold,
    )


def assemble(
    build: ThemeBuild,
    *,
    threshold: float = DEFAULT_COMPLETENESS_THRESHOLD,
    override: OverrideLog | None = None,
) -> AssembledGraph:
    """Best-effort assembly: always surface the graph we have.

    Only schema-valid SuppliesEdges are admitted (fully-provenanced figures); every gap edge
    becomes a drawn ghost edge. Completeness is reported but never withholds the graph — only a
    truly empty build (no publishable AND no gap edges) stays unassembled. ``override``, when an
    admin publishes below the recommended completeness threshold, is recorded for the audit log.
    """
    # Re-validate at the publish boundary: only edges meeting schema rules are admitted.
    edges = [e for e in build.edges if is_valid("SuppliesEdge", e)]
    report = _completeness(len(edges), len(build.gap_edges), threshold)

    if report.total_edges == 0:
        # Nothing — no quantified relationship and no gap to draw. Can't publish an empty graph.
        return AssembledGraph(
            theme_id=build.theme_id,
            version=build.version,
            assembled=False,
            completeness=report,
        )

    if not report.meets_threshold:
        # Best-effort: still assemble, but note the low-completeness publish (and any override).
        logger.info(
            "best-effort assembly below threshold: theme=%s version=%s completeness=%.2f "
            "threshold=%.2f publishable=%d gaps=%d%s",
            build.theme_id,
            build.version,
            report.completeness,
            threshold,
            report.publishable_edges,
            report.gap_edges,
            f" override_actor={override.actor!r} reason={override.reason!r}"
            if override is not None
            else "",
        )

    admitted_tickers = {t for e in edges for t in (e["supplier"], e["customer"])}
    admitted_tickers |= {t for g in build.gap_edges for t in (g.supplier, g.customer)}
    companies = [c for c in build.companies if c["ticker"] in admitted_tickers]

    admitted_keys = {f"{e['supplier']}->{e['customer']}" for e in edges}
    edge_sources = {k: v for k, v in build.edge_sources.items() if k in admitted_keys}
    edge_details = {k: v for k, v in build.edge_details.items() if k in admitted_keys}

    return AssembledGraph(
        theme_id=build.theme_id,
        version=build.version,
        assembled=True,
        completeness=report,
        override=override,
        companies=companies,
        edges=edges,
        ghost_edges=list(build.gap_edges),
        edge_sources=edge_sources,
        edge_details=edge_details,
    )
