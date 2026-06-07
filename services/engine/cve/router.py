"""CVE run endpoint — trigger the S0-S7 pipeline for a theme and persist a build."""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from services.engine.background import run_detached
from services.engine.blueprint.repository import BlueprintRepository
from services.engine.blueprint.router import get_blueprint_repository, get_router
from services.engine.calendar.repository import (
    CalendarRepository,
    PostgresCalendarRepository,
)
from services.engine.cve.run_repository import CveRunRepository, PostgresCveRunRepository
from services.engine.cve.run_service import (
    CveRunSummary,
    research_and_build_events,
    run_cve_events_for_theme,
    run_cve_for_theme,
)
from services.engine.db.config import DbSettings
from services.engine.db.graph_store import GraphStore
from services.engine.financials.repository import FinancialsRepository
from services.engine.financials.router import get_financials_repository
from services.engine.llm.router import LLMRouter
from services.engine.publish.router import get_graph_store
from services.engine.sse import sse_response
from services.engine.storage import Storage
from services.engine.themes.repository import ThemeRepository
from services.engine.themes.router import get_repository as get_theme_repository
from services.engine.themes.router import get_storage
from services.engine.tickets.repository import TicketRepository
from services.engine.tickets.router import get_ticket_repository

logger = logging.getLogger("valuegraph.engine.cve")

router = APIRouter(tags=["cve"])


def get_cve_run_repository() -> CveRunRepository:
    return PostgresCveRunRepository(DbSettings.from_env())


def get_calendar_repository() -> CalendarRepository:
    return PostgresCalendarRepository(DbSettings.from_env())


ThemeRepoDep = Annotated[ThemeRepository, Depends(get_theme_repository)]
BlueprintRepoDep = Annotated[BlueprintRepository, Depends(get_blueprint_repository)]
TicketRepoDep = Annotated[TicketRepository, Depends(get_ticket_repository)]
RouterDep = Annotated[LLMRouter, Depends(get_router)]
StorageDep = Annotated[Storage, Depends(get_storage)]
GraphStoreDep = Annotated[GraphStore, Depends(get_graph_store)]
CveRunRepoDep = Annotated[CveRunRepository, Depends(get_cve_run_repository)]
CalendarRepoDep = Annotated[CalendarRepository, Depends(get_calendar_repository)]
FinancialsRepoDep = Annotated[FinancialsRepository, Depends(get_financials_repository)]


@router.post("/themes/{theme_id}/cve/run", response_model=CveRunSummary)
def run_theme_cve(
    theme_id: str,
    themes: ThemeRepoDep,
    blueprints: BlueprintRepoDep,
    tickets: TicketRepoDep,
    llm: RouterDep,
    storage: StorageDep,
    graph: GraphStoreDep,
    runs: CveRunRepoDep,
    calendar: CalendarRepoDep,
    financials: FinancialsRepoDep,
) -> CveRunSummary:
    """Run the CVE pipeline over the theme's current sources + tickets and persist the
    next Staging build (the artifact Publish consumes). Reflects ticket state (incl. the
    not-disclosed 10% bound) and the disclosure calendar."""
    theme = themes.get_theme(theme_id)
    if theme is None:
        raise HTTPException(status_code=404, detail="theme not found")
    blueprint = blueprints.get_latest(theme_id)
    if blueprint is None:
        raise HTTPException(
            status_code=409, detail="no blueprint to build from; generate one first"
        )
    sources = themes.list_sources(theme_id)
    logger.info("cve.request theme=%s sources=%d", theme_id, len(sources))
    return run_cve_for_theme(
        theme_id=theme_id,
        blueprint=blueprint,
        sources=sources,
        storage=storage,
        router=llm,
        ticket_repo=tickets,
        graph_store=graph,
        run_repo=runs,
        calendar_repo=calendar,
        financials_repo=financials,
        today=date.today().isoformat(),
    )


@router.post("/themes/{theme_id}/cve/run/stream")
def stream_theme_cve(
    theme_id: str,
    themes: ThemeRepoDep,
    blueprints: BlueprintRepoDep,
    tickets: TicketRepoDep,
    llm: RouterDep,
    storage: StorageDep,
    graph: GraphStoreDep,
    runs: CveRunRepoDep,
    calendar: CalendarRepoDep,
    financials: FinancialsRepoDep,
) -> StreamingResponse:
    """Run the CVE pipeline as a live SSE stream (per-stage S1-S7 progress + the build
    summary). Detached: the run + persistence finish even if the admin closes the tab."""
    theme = themes.get_theme(theme_id)
    if theme is None:
        raise HTTPException(status_code=404, detail="theme not found")
    blueprint = blueprints.get_latest(theme_id)
    if blueprint is None:
        raise HTTPException(
            status_code=409, detail="no blueprint to build from; generate one first"
        )
    sources = themes.list_sources(theme_id)
    logger.info("cve.stream request theme=%s sources=%d", theme_id, len(sources))
    return sse_response(
        run_detached(
            lambda: run_cve_events_for_theme(
                theme_id=theme_id,
                blueprint=blueprint,
                sources=sources,
                storage=storage,
                router=llm,
                ticket_repo=tickets,
                graph_store=graph,
                run_repo=runs,
                calendar_repo=calendar,
                financials_repo=financials,
                today=date.today().isoformat(),
            ),
            label=f"cve-run:{theme_id}",
        )
    )


@router.post("/themes/{theme_id}/cve/research/stream")
def stream_research_and_build(
    theme_id: str,
    themes: ThemeRepoDep,
    blueprints: BlueprintRepoDep,
    tickets: TicketRepoDep,
    llm: RouterDep,
    storage: StorageDep,
    graph: GraphStoreDep,
    runs: CveRunRepoDep,
    calendar: CalendarRepoDep,
    financials: FinancialsRepoDep,
) -> StreamingResponse:
    """One streamed action: Deep Research the chain (trades + financials) into the graph,
    then build it; what can't be sourced becomes tickets. Detached: finishes even if the
    admin closes the tab."""
    theme = themes.get_theme(theme_id)
    if theme is None:
        raise HTTPException(status_code=404, detail="theme not found")
    blueprint = blueprints.get_latest(theme_id)
    if blueprint is None:
        raise HTTPException(
            status_code=409, detail="no blueprint to research; generate one first"
        )
    sources = themes.list_sources(theme_id)
    logger.info("cve.research request theme=%s sources=%d", theme_id, len(sources))
    return sse_response(
        run_detached(
            lambda: research_and_build_events(
                theme=theme,
                blueprint=blueprint,
                sources=sources,
                storage=storage,
                router=llm,
                ticket_repo=tickets,
                theme_repo=themes,
                graph_store=graph,
                run_repo=runs,
                calendar_repo=calendar,
                financials_repo=financials,
                today=date.today().isoformat(),
            ),
            label=f"cve-research:{theme_id}",
        )
    )
