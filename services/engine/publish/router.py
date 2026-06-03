"""Read-only Production endpoints — the seam Terminal reads (graph + data quality).

[M4-DQ-05] data-quality meter · [M5-CANVAS-01] published graph for the 3D canvas.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from services.engine.db.artifacts import GapEdge
from services.engine.db.config import DbSettings
from services.engine.publish.publish import PostgresProductionStore, ProductionStore
from services.engine.publish.quality import QualityReport, compute_quality

router = APIRouter(tags=["publish"])


class PublishedGraph(BaseModel):
    """The current published graph a Terminal renders (Production, read-only)."""

    theme_id: str
    snapshot_version: int
    completeness: float
    companies: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    ghost_edges: list[GapEdge] = Field(default_factory=list)
    edge_sources: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


def get_production_store() -> ProductionStore:
    return PostgresProductionStore(DbSettings.from_env())


ProductionStoreDep = Annotated[ProductionStore, Depends(get_production_store)]


@router.get("/themes/{theme_id}/quality", response_model=QualityReport)
def theme_quality(theme_id: str, store: ProductionStoreDep) -> QualityReport:
    """The verified/derived/estimated/gap mix of a theme's currently published graph."""
    snapshot = store.current(theme_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="no published snapshot for theme")
    return compute_quality(snapshot)


@router.get("/themes/{theme_id}/graph", response_model=PublishedGraph)
def theme_graph(theme_id: str, store: ProductionStoreDep) -> PublishedGraph:
    """The currently published supply-chain graph the Terminal 3D canvas renders."""
    snapshot = store.current(theme_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="no published snapshot for theme")
    return PublishedGraph(
        theme_id=snapshot.theme_id,
        snapshot_version=snapshot.snapshot_version,
        completeness=snapshot.completeness,
        companies=snapshot.companies,
        edges=snapshot.edges,
        ghost_edges=snapshot.ghost_edges,
        edge_sources=snapshot.edge_sources,
    )
