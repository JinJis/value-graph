"""Blueprint generation endpoints (PRD §8.2). Round-1 generation + persistence;
iterative refinement (2-3 rounds) is [M1-BLU-03]."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.engine.blueprint.coverage import summarize
from services.engine.blueprint.discover import discover_companies
from services.engine.blueprint.domains import fill_blueprint_domains
from services.engine.blueprint.generate import generate_blueprint
from services.engine.blueprint.models import (
    Blueprint,
    BlueprintContent,
    BlueprintRecord,
    BlueprintResponse,
    DiscoveryResult,
    RefinementResult,
)
from services.engine.blueprint.prompt import DEFAULT_TARGET_COMPANIES
from services.engine.blueprint.refine import refine_blueprint
from services.engine.blueprint.repository import (
    BlueprintRepository,
    PostgresBlueprintRepository,
)
from services.engine.blueprint.stream import (
    discover_companies_events,
    generate_blueprint_events,
    refine_blueprint_events,
)
from services.engine.db.config import DbSettings
from services.engine.llm.router import LLMRouter
from services.engine.sse import task_sse
from services.engine.themes.models import Theme
from services.engine.themes.repository import ThemeRepository
from services.engine.themes.router import get_repository as get_theme_repository

router = APIRouter(tags=["blueprint"])

# Admin-selectable blueprint size (slider bounds; the prompt aims for this many companies).
MIN_TARGET_COMPANIES = 5
MAX_TARGET_COMPANIES = 80

# A query param for the target company count, clamped to the allowed range.
CountQuery = Annotated[
    int, Query(ge=MIN_TARGET_COMPANIES, le=MAX_TARGET_COMPANIES, alias="count")
]


def get_blueprint_repository() -> BlueprintRepository:
    return PostgresBlueprintRepository(DbSettings.from_env())


def get_router() -> LLMRouter:
    return LLMRouter.from_env()


ThemeRepoDep = Annotated[ThemeRepository, Depends(get_theme_repository)]
BlueprintRepoDep = Annotated[BlueprintRepository, Depends(get_blueprint_repository)]
RouterDep = Annotated[LLMRouter, Depends(get_router)]


@router.post("/themes/{theme_id}/blueprint", response_model=BlueprintResponse, status_code=201)
def generate_theme_blueprint(
    theme_id: str,
    themes: ThemeRepoDep,
    blueprints: BlueprintRepoDep,
    llm: RouterDep,
    count: CountQuery = DEFAULT_TARGET_COMPANIES,
) -> BlueprintResponse:
    theme = themes.get_theme(theme_id)
    if theme is None:
        raise HTTPException(status_code=404, detail="theme not found")
    source_hints = [
        f"{s.original_filename or s.url or s.id} ({s.type})"
        for s in themes.list_sources(theme_id)
    ]
    version = blueprints.next_version(theme_id)
    blueprint = generate_blueprint(
        theme, source_hints, llm, version=version, theme_repo=themes, target_count=count
    )
    record = blueprints.save(blueprint)
    return BlueprintResponse(blueprint=record, coverage=summarize(record))


@router.post("/themes/{theme_id}/blueprint/stream")
def stream_theme_blueprint(
    theme_id: str,
    themes: ThemeRepoDep,
    blueprints: BlueprintRepoDep,
    llm: RouterDep,
    count: CountQuery = DEFAULT_TARGET_COMPANIES,
) -> StreamingResponse:
    """Generate the blueprint as a live Server-Sent Events stream.

    Same generation + persistence as POST ``/blueprint`` but observable: emits the
    routed agent, the endpoint, the exact prompt, the report as it streams (plus the
    agent's live search/reasoning progress), and the saved result. The Deep Research
    run takes minutes; streaming keeps the connection alive and shows progress
    instead of looking like a hung request.
    """
    theme = themes.get_theme(theme_id)
    if theme is None:
        raise HTTPException(status_code=404, detail="theme not found")
    source_hints = [
        f"{s.original_filename or s.url or s.id} ({s.type})"
        for s in themes.list_sources(theme_id)
    ]
    return task_sse(
        theme_id=theme_id,
        kind="blueprint-generate",
        label="Blueprint generation",
        factory=lambda: generate_blueprint_events(
            theme, source_hints, llm, blueprints, themes, target_count=count
        ),
    )


@router.post("/themes/{theme_id}/blueprint/refine/stream")
def stream_refine_blueprint(
    theme_id: str,
    themes: ThemeRepoDep,
    blueprints: BlueprintRepoDep,
    llm: RouterDep,
) -> StreamingResponse:
    """Iterative refinement (2-3 DEEP rounds) as a live SSE stream — one round per
    DEEP call, with merge/convergence events between rounds."""
    theme = themes.get_theme(theme_id)
    if theme is None:
        raise HTTPException(status_code=404, detail="theme not found")
    base = blueprints.get_latest(theme_id)
    if base is None:
        raise HTTPException(status_code=409, detail="no blueprint to refine; generate one first")
    return task_sse(
        theme_id=theme_id,
        kind="blueprint-refine",
        label="Blueprint refinement",
        factory=lambda: refine_blueprint_events(theme, base, llm, blueprints),
    )


@router.post("/themes/{theme_id}/blueprint/discover/stream")
def stream_discover_constituents(
    theme_id: str,
    themes: ThemeRepoDep,
    blueprints: BlueprintRepoDep,
    llm: RouterDep,
) -> StreamingResponse:
    """RESEARCH discovery pass as a live SSE stream — broaden constituents, attribute
    each to a Source, merge into the plan."""
    theme = themes.get_theme(theme_id)
    if theme is None:
        raise HTTPException(status_code=404, detail="theme not found")
    base = blueprints.get_latest(theme_id)
    if base is None:
        raise HTTPException(status_code=409, detail="no blueprint to extend; generate one first")
    return task_sse(
        theme_id=theme_id,
        kind="blueprint-discover",
        label="Blueprint discovery",
        factory=lambda: discover_companies_events(theme, base, llm, blueprints, themes),
    )


@router.post("/themes/{theme_id}/blueprint/refine", response_model=RefinementResult)
def refine_theme_blueprint(
    theme_id: str,
    themes: ThemeRepoDep,
    blueprints: BlueprintRepoDep,
    llm: RouterDep,
) -> RefinementResult:
    theme = themes.get_theme(theme_id)
    if theme is None:
        raise HTTPException(status_code=404, detail="theme not found")
    base = blueprints.get_latest(theme_id)
    if base is None:
        raise HTTPException(status_code=409, detail="no blueprint to refine; generate one first")
    return refine_blueprint(theme, base, llm, blueprints)


@router.post("/themes/{theme_id}/blueprint/discover", response_model=DiscoveryResult)
def discover_theme_constituents(
    theme_id: str,
    themes: ThemeRepoDep,
    blueprints: BlueprintRepoDep,
    llm: RouterDep,
) -> DiscoveryResult:
    theme = themes.get_theme(theme_id)
    if theme is None:
        raise HTTPException(status_code=404, detail="theme not found")
    base = blueprints.get_latest(theme_id)
    if base is None:
        raise HTTPException(status_code=409, detail="no blueprint to extend; generate one first")
    return discover_companies(theme, base, llm, blueprints, themes)


@router.put("/themes/{theme_id}/blueprint", response_model=BlueprintResponse)
def save_theme_blueprint(
    theme_id: str,
    content: BlueprintContent,
    themes: ThemeRepoDep,
    blueprints: BlueprintRepoDep,
) -> BlueprintResponse:
    """Persist an admin-edited blueprint as a new version (PRD §8.2 review)."""
    if themes.get_theme(theme_id) is None:
        raise HTTPException(status_code=404, detail="theme not found")
    version = blueprints.next_version(theme_id)
    previous = blueprints.get_latest(theme_id)  # preserve the chosen target across edits
    record = blueprints.save(
        Blueprint(
            theme_id=theme_id,
            version=version,
            generated_by="admin (manual edit)",
            companies=content.companies,
            relationship_types=content.relationship_types,
            notes=content.notes,
            target_count=previous.target_count if previous else None,
        )
    )
    return BlueprintResponse(blueprint=record, coverage=summarize(record))


class FillDomainsResult(BaseModel):
    filled: int
    total: int
    blueprint: BlueprintRecord


@router.post("/themes/{theme_id}/blueprint/fill-domains", response_model=FillDomainsResult)
def fill_theme_blueprint_domains(
    theme_id: str,
    themes: ThemeRepoDep,
    blueprints: BlueprintRepoDep,
    llm: RouterDep,
) -> FillDomainsResult:
    """Backfill each company's website domain (for accurate Terminal logos) with a cheap
    LOW-tier call, saving a new blueprint version. Idempotent: only fills blanks. Re-run the
    Build + Publish afterwards so the published nodes pick up the logos."""
    if themes.get_theme(theme_id) is None:
        raise HTTPException(status_code=404, detail="theme not found")
    base = blueprints.get_latest(theme_id)
    if base is None:
        raise HTTPException(status_code=409, detail="no blueprint; generate one first")
    updated, filled = fill_blueprint_domains(base.companies, llm)
    if filled == 0:
        return FillDomainsResult(filled=0, total=len(base.companies), blueprint=base)
    record = blueprints.save(
        Blueprint(
            theme_id=theme_id,
            version=blueprints.next_version(theme_id),
            generated_by="domain backfill",
            companies=updated,
            relationship_types=base.relationship_types,
            notes=base.notes,
            target_count=base.target_count,
        )
    )
    return FillDomainsResult(filled=filled, total=len(base.companies), blueprint=record)


@router.post("/themes/{theme_id}/blueprint/approve", response_model=Theme)
def approve_theme_blueprint(
    theme_id: str,
    themes: ThemeRepoDep,
    blueprints: BlueprintRepoDep,
) -> Theme:
    """Approve the blueprint -> advance the theme to ticketing (M2)."""
    if themes.get_theme(theme_id) is None:
        raise HTTPException(status_code=404, detail="theme not found")
    if blueprints.get_latest(theme_id) is None:
        raise HTTPException(status_code=409, detail="no blueprint to approve; generate one first")
    updated = themes.set_status(theme_id, "approved")
    if updated is None:
        raise HTTPException(status_code=404, detail="theme not found")
    return updated


@router.get("/themes/{theme_id}/blueprint", response_model=BlueprintResponse)
def get_theme_blueprint(
    theme_id: str,
    themes: ThemeRepoDep,
    blueprints: BlueprintRepoDep,
) -> BlueprintResponse:
    if themes.get_theme(theme_id) is None:
        raise HTTPException(status_code=404, detail="theme not found")
    record = blueprints.get_latest(theme_id)
    if record is None:
        raise HTTPException(status_code=404, detail="no blueprint generated yet")
    return BlueprintResponse(blueprint=record, coverage=summarize(record))
