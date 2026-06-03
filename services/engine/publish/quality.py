"""[M4-DQ-05] Theme data-quality meter — the verified/derived/estimated/gap mix.

Computed from the published graph (Production snapshot): how much of a theme's
supply chain is corroborated vs derived vs merely estimated vs an open gap. This is
the honest-about-uncertainty headline number, shown in Studio and (read-only) in
Terminal. Gap counts the drawn ghost edges, so gaps weigh on the score — never
hidden.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from graph_schema import is_valid
from services.engine.publish.publish import ProductionSnapshot

CONFIDENCE_TIERS = ("verified", "derived", "estimated")


class QualityCounts(BaseModel):
    verified: int = 0
    derived: int = 0
    estimated: int = 0
    gap: int = 0

    @property
    def total(self) -> int:
        return self.verified + self.derived + self.estimated + self.gap


class DataQuality(BaseModel):
    """Tier mix as percentages of all relationships (mirrors graph-schema DataQuality)."""

    verified: float
    derived: float
    estimated: float
    gap: float


class QualityReport(BaseModel):
    theme_id: str
    snapshot_version: int
    counts: QualityCounts
    total: int
    quality: DataQuality


def _percentages(counts: QualityCounts) -> DataQuality:
    total = counts.total

    def pct(n: int) -> float:
        return round(n / total * 100, 1) if total else 0.0

    quality = DataQuality(
        verified=pct(counts.verified),
        derived=pct(counts.derived),
        estimated=pct(counts.estimated),
        gap=pct(counts.gap),
    )
    # Stays within the canonical schema (each tier in [0, 100]).
    assert is_valid("DataQuality", quality.model_dump())
    return quality


def count_quality(edges: list[dict[str, Any]], gap_count: int) -> QualityCounts:
    """Tally edges by confidence tier; ``gap_count`` is the number of ghost edges."""
    counts = QualityCounts(gap=gap_count)
    for edge in edges:
        tier = edge.get("confidence")
        if tier == "verified":
            counts.verified += 1
        elif tier == "derived":
            counts.derived += 1
        elif tier == "estimated":
            counts.estimated += 1
    return counts


def compute_quality(snapshot: ProductionSnapshot) -> QualityReport:
    """The data-quality meter for a published Production snapshot."""
    counts = count_quality(snapshot.edges, len(snapshot.ghost_edges))
    return QualityReport(
        theme_id=snapshot.theme_id,
        snapshot_version=snapshot.snapshot_version,
        counts=counts,
        total=counts.total,
        quality=_percentages(counts),
    )
