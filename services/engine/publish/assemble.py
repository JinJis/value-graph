"""[M4-ASM-02] Graph assembly — turn a persisted ThemeBuild into a publishable graph.

Once a theme build's completeness clears a configurable threshold (or an admin
explicitly overrides, which is logged), assemble the publishable supply-chain
graph: nodes + only the edges that meet the SuppliesEdge schema rules, plus the
gap edges carried as drawn "ghost" edges (they expose no figure, so they don't
violate the validation gate — gaps are drawn, never hidden).

Completeness here = quantified relationships / all discovered relationships
(publishable edges / (publishable + gap edges)). Blueprint-coverage refinements
can plug into this metric later. The validation gate (every exposed figure carries
source + as_of + next_update + confidence + interval) is M4-GATE-03; publish to
Production is M4-PUB-04.
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
    """Assemble ``build`` into a publishable graph if complete enough (or overridden).

    Only schema-valid SuppliesEdges are admitted; gap edges become drawn ghost edges.
    When completeness is below ``threshold`` and no ``override`` is given, the graph
    is withheld (``assembled=False``) with a report explaining why.
    """
    # Re-validate at the publish boundary: only edges meeting schema rules are admitted.
    edges = [e for e in build.edges if is_valid("SuppliesEdge", e)]
    report = _completeness(len(edges), len(build.gap_edges), threshold)

    if report.meets_threshold:
        admitted = True
    elif override is not None:
        admitted = True
        logger.warning(
            "assembly override: theme=%s version=%s actor=%s reason=%r "
            "completeness=%.2f threshold=%.2f",
            build.theme_id,
            build.version,
            override.actor,
            override.reason,
            report.completeness,
            threshold,
        )
    else:
        admitted = False

    if not admitted:
        # Withhold the graph; surface the report so the admin can improve or override.
        return AssembledGraph(
            theme_id=build.theme_id,
            version=build.version,
            assembled=False,
            completeness=report,
        )

    admitted_tickers = {t for e in edges for t in (e["supplier"], e["customer"])}
    admitted_tickers |= {t for g in build.gap_edges for t in (g.supplier, g.customer)}
    companies = [c for c in build.companies if c["ticker"] in admitted_tickers]

    return AssembledGraph(
        theme_id=build.theme_id,
        version=build.version,
        assembled=True,
        completeness=report,
        override=override,
        companies=companies,
        edges=edges,
        ghost_edges=list(build.gap_edges),
    )
