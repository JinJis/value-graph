"""[M4-GATE-03] Validation gate — block publish unless every exposed figure is fully provenanced.

Hard invariant (CLAUDE.md #3/#4): every exposed figure carries a Source + as_of_date
+ next_expected_update + confidence + interval; no number enters the graph without a
Source. This gate inspects an assembled graph's publishable edges (the figures that
carry numbers) and reports every violation. Publish stays disabled until the report
is clean or an admin supplies an explicit, logged override.

Ghost edges expose no figure, so they are not gated. Node market_cap/price are
real-time, nullable (node size, licensed feed) and not periodic-figure provenance —
out of this gate's scope.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from services.engine.db.artifacts import ThemeBuild
from services.engine.publish.assemble import AssembledGraph, OverrideLog

logger = logging.getLogger(__name__)

# Provenance every exposed figure must carry (CLAUDE.md invariant #3).
REQUIRED_FIGURE_FIELDS = ("as_of_date", "next_expected_update", "confidence", "confidence_interval")


class Violation(BaseModel):
    edge: str  # "SUPPLIER->CUSTOMER"
    field: str  # source | as_of_date | next_expected_update | confidence | confidence_interval
    detail: str


class GateReport(BaseModel):
    theme_id: str
    version: int
    checked_edges: int
    violations: list[Violation] = Field(default_factory=list)
    clean: bool
    override: OverrideLog | None = None
    passed: bool  # clean, or overridden — publish is allowed only when this is True


def _edge_label(edge: dict[str, object]) -> str:
    return f"{edge.get('supplier')}->{edge.get('customer')}"


def _figure_violations(edge: dict[str, object], sourced: set[tuple[str, str]]) -> list[Violation]:
    label = _edge_label(edge)
    out: list[Violation] = []

    key = (edge.get("supplier"), edge.get("customer"))
    if key not in sourced:
        out.append(Violation(edge=label, field="source", detail="no Source-backed claim for edge"))

    for field in REQUIRED_FIGURE_FIELDS:
        value = edge.get(field)
        if value in (None, ""):
            out.append(Violation(edge=label, field=field, detail=f"missing {field}"))

    interval = edge.get("confidence_interval")
    if isinstance(interval, dict):
        low, high = interval.get("low"), interval.get("high")
        if low is None or high is None:
            out.append(
                Violation(
                    edge=label, field="confidence_interval", detail="interval missing low/high"
                )
            )
        elif low > high:
            out.append(
                Violation(
                    edge=label,
                    field="confidence_interval",
                    detail=f"interval inverted (low {low} > high {high})",
                )
            )
    return out


def gate(
    assembled: AssembledGraph,
    build: ThemeBuild,
    *,
    override: OverrideLog | None = None,
) -> GateReport:
    """Validate every exposed figure in ``assembled``; publish is allowed only if it passes.

    ``build`` supplies the claim->Source backing used to enforce "no number without a
    Source". When violations remain, an explicit ``override`` lets publish proceed and
    is logged (audited).
    """
    if not assembled.assembled:
        # A withheld graph never reaches the gate clean.
        return GateReport(
            theme_id=assembled.theme_id,
            version=assembled.version,
            checked_edges=0,
            violations=[
                Violation(edge="-", field="assembly", detail="graph not assembled (incomplete)")
            ],
            clean=False,
            passed=False,
        )

    # Edges backed by at least one claim whose Source node exists.
    sourced = {
        (claim["subject"], claim["object"])
        for claim in build.claims
        if claim.get("source_id") in build.sources
    }

    violations: list[Violation] = []
    for edge in assembled.edges:
        violations.extend(_figure_violations(edge, sourced))

    clean = not violations
    if clean:
        passed = True
    elif override is not None:
        passed = True
        logger.warning(
            "validation-gate override: theme=%s version=%s actor=%s reason=%r violations=%d",
            assembled.theme_id,
            assembled.version,
            override.actor,
            override.reason,
            len(violations),
        )
    else:
        passed = False

    return GateReport(
        theme_id=assembled.theme_id,
        version=assembled.version,
        checked_edges=len(assembled.edges),
        violations=violations,
        clean=clean,
        override=override if not clean else None,
        passed=passed,
    )
