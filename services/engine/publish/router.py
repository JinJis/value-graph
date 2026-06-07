"""Read-only Production endpoints — the seam Terminal reads (graph + data quality).

[M4-DQ-05] data-quality meter · [M5-CANVAS-01] published graph for the 3D canvas.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from services.engine.db.artifacts import GapEdge
from services.engine.db.config import DbSettings
from services.engine.db.graph import connect
from services.engine.db.graph_store import GraphStore, Neo4jGraphStore
from services.engine.publish.assemble import (
    DEFAULT_COMPLETENESS_THRESHOLD,
    CompletenessReport,
    OverrideLog,
    assemble,
)
from services.engine.publish.gate import GateReport, gate
from services.engine.publish.publish import (
    PostgresProductionStore,
    ProductionStore,
    PublishBlocked,
    publish,
)
from services.engine.publish.quality import QualityReport, compute_quality
from services.engine.themes.repository import ThemeRepository
from services.engine.themes.router import get_repository as get_theme_repository

logger = logging.getLogger("valuegraph.engine.publish")

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
    edge_details: dict[str, dict[str, Any]] = Field(default_factory=dict)


def get_production_store() -> ProductionStore:
    return PostgresProductionStore(DbSettings.from_env())


def get_graph_store() -> GraphStore:
    return Neo4jGraphStore(connect(DbSettings.from_env()))


ProductionStoreDep = Annotated[ProductionStore, Depends(get_production_store)]
GraphStoreDep = Annotated[GraphStore, Depends(get_graph_store)]
ThemeRepoDep = Annotated[ThemeRepository, Depends(get_theme_repository)]


class PublishPreview(BaseModel):
    """Whether the latest Staging build can be published, and what blocks it."""

    theme_id: str
    build_version: int
    completeness: CompletenessReport
    gate: GateReport
    can_publish: bool  # clean gate + meets completeness threshold (no override needed)


class PublishRequest(BaseModel):
    """Publish the latest Staging build to Production (explicit human action)."""

    actor: str = "admin"  # no auth yet; captured for the audit log
    override_reason: str | None = None  # required to publish past gate/completeness issues
    threshold: float | None = None  # completeness bar; defaults to the engine default


class PublishResult(BaseModel):
    theme_id: str
    snapshot_version: int
    source_build_version: int
    completeness: float
    published_by: str
    published_at: datetime
    edges: int
    ghost_edges: int
    overridden: bool


@router.get("/themes/{theme_id}/publish/preview", response_model=PublishPreview)
def preview_publish(
    theme_id: str,
    themes: ThemeRepoDep,
    graph: GraphStoreDep,
    threshold: Annotated[float, Query()] = DEFAULT_COMPLETENESS_THRESHOLD,
) -> PublishPreview:
    """Assemble + gate the latest build WITHOUT writing — surfaces completeness and every
    validation violation so the admin can decide whether to publish (or override)."""
    if themes.get_theme(theme_id) is None:
        raise HTTPException(status_code=404, detail="theme not found")
    build = graph.load_latest(theme_id)
    if build is None:
        raise HTTPException(status_code=409, detail="no CVE build to publish; run CVE first")
    assembled = assemble(build, threshold=threshold)
    report = gate(assembled, build)
    return PublishPreview(
        theme_id=theme_id,
        build_version=build.version,
        completeness=assembled.completeness,
        gate=report,
        can_publish=report.passed,
    )


@router.post("/themes/{theme_id}/publish", response_model=PublishResult)
def publish_theme(
    theme_id: str,
    req: PublishRequest,
    themes: ThemeRepoDep,
    graph: GraphStoreDep,
    store: ProductionStoreDep,
) -> PublishResult:
    """Publish the latest Staging build to Production as a new read-only snapshot.

    Explicit human action: requires an ``actor``. Validation issues (incomplete graph or
    an exposed figure missing provenance) block publish unless an ``override_reason`` is
    supplied, which is logged.
    """
    if themes.get_theme(theme_id) is None:
        raise HTTPException(status_code=404, detail="theme not found")
    if not req.actor.strip():
        raise HTTPException(status_code=400, detail="publish requires an actor")
    build = graph.load_latest(theme_id)
    if build is None:
        raise HTTPException(status_code=409, detail="no CVE build to publish; run CVE first")

    threshold = req.threshold if req.threshold is not None else DEFAULT_COMPLETENESS_THRESHOLD
    reason = (req.override_reason or "").strip()
    override = OverrideLog(actor=req.actor, reason=reason) if reason else None

    assembled = assemble(build, threshold=threshold, override=override)
    report = gate(assembled, build, override=override)
    if not report.passed:
        raise HTTPException(
            status_code=409,
            detail=(
                f"publish blocked: {len(report.violations)} unresolved validation "
                "issue(s); supply an override reason to publish anyway"
            ),
        )

    try:
        snap = publish(assembled, report, store, actor=req.actor)
    except PublishBlocked as exc:  # defensive; report.passed already checked
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    logger.info(
        "publish.endpoint theme=%s snapshot_version=%s build=%s by=%s overridden=%s",
        theme_id,
        snap.snapshot_version,
        snap.source_build_version,
        req.actor,
        override is not None,
    )
    return PublishResult(
        theme_id=snap.theme_id,
        snapshot_version=snap.snapshot_version,
        source_build_version=snap.source_build_version,
        completeness=snap.completeness,
        published_by=snap.published_by,
        published_at=snap.published_at,
        edges=len(snap.edges),
        ghost_edges=len(snap.ghost_edges),
        overridden=override is not None,
    )


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
        edge_details=snapshot.edge_details,
    )
