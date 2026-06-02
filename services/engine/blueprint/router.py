"""Blueprint generation endpoints (PRD §8.2). Round-1 generation + persistence;
iterative refinement (2-3 rounds) is [M1-BLU-03]."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from services.engine.blueprint.coverage import summarize
from services.engine.blueprint.discover import discover_companies
from services.engine.blueprint.generate import generate_blueprint
from services.engine.blueprint.models import (
    Blueprint,
    BlueprintContent,
    BlueprintResponse,
    DiscoveryResult,
    RefinementResult,
)
from services.engine.blueprint.refine import refine_blueprint
from services.engine.blueprint.repository import (
    BlueprintRepository,
    PostgresBlueprintRepository,
)
from services.engine.db.config import DbSettings
from services.engine.llm.router import LLMRouter
from services.engine.themes.models import Theme
from services.engine.themes.repository import ThemeRepository
from services.engine.themes.router import get_repository as get_theme_repository

router = APIRouter(tags=["blueprint"])


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
) -> BlueprintResponse:
    theme = themes.get_theme(theme_id)
    if theme is None:
        raise HTTPException(status_code=404, detail="theme not found")
    source_hints = [
        f"{s.original_filename or s.url or s.id} ({s.type})"
        for s in themes.list_sources(theme_id)
    ]
    version = blueprints.next_version(theme_id)
    blueprint = generate_blueprint(theme, source_hints, llm, version=version)
    record = blueprints.save(blueprint)
    return BlueprintResponse(blueprint=record, coverage=summarize(record))


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
    record = blueprints.save(
        Blueprint(
            theme_id=theme_id,
            version=version,
            generated_by="admin (manual edit)",
            companies=content.companies,
            relationship_types=content.relationship_types,
            notes=content.notes,
        )
    )
    return BlueprintResponse(blueprint=record, coverage=summarize(record))


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
