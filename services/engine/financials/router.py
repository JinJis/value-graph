"""Per-company financials endpoints — admin-entered complementary-side figures."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from services.engine.blueprint.repository import BlueprintRepository
from services.engine.blueprint.router import get_blueprint_repository, get_router
from services.engine.db.config import DbSettings
from services.engine.financials.models import FinancialsRecord, FinancialsUpsert
from services.engine.financials.repository import (
    FinancialsRepository,
    PostgresFinancialsRepository,
)
from services.engine.financials.research import research_financials_events
from services.engine.llm.router import LLMRouter
from services.engine.sse import task_sse
from services.engine.themes.repository import ThemeRepository
from services.engine.themes.router import get_repository as get_theme_repository

router = APIRouter(tags=["financials"])


def get_financials_repository() -> FinancialsRepository:
    return PostgresFinancialsRepository(DbSettings.from_env())


FinancialsRepoDep = Annotated[FinancialsRepository, Depends(get_financials_repository)]
ThemeRepoDep = Annotated[ThemeRepository, Depends(get_theme_repository)]
BlueprintRepoDep = Annotated[BlueprintRepository, Depends(get_blueprint_repository)]
RouterDep = Annotated[LLMRouter, Depends(get_router)]


@router.get("/financials", response_model=list[FinancialsRecord])
def list_financials(
    repo: FinancialsRepoDep,
    tickers: Annotated[str | None, Query()] = None,
) -> list[FinancialsRecord]:
    """List financials, optionally restricted to a comma-separated ``tickers`` set."""
    wanted = [t.strip() for t in tickers.split(",") if t.strip()] if tickers else None
    return repo.list_for(wanted)


@router.put("/financials/{ticker}", response_model=FinancialsRecord)
def upsert_financials(
    ticker: str, data: FinancialsUpsert, repo: FinancialsRepoDep
) -> FinancialsRecord:
    """Create/replace a company's financials (path ticker wins over the body)."""
    return repo.upsert(data.model_copy(update={"company_ticker": ticker}))


@router.post("/themes/{theme_id}/financials/research/stream")
def stream_research_financials(
    theme_id: str,
    themes: ThemeRepoDep,
    blueprints: BlueprintRepoDep,
    repo: FinancialsRepoDep,
    llm: RouterDep,
) -> StreamingResponse:
    """Deep Research the blueprint companies' financials (revenue + cost buckets) and fill
    the store, as a live SSE stream. Detached: finishes even if the admin closes the tab."""
    theme = themes.get_theme(theme_id)
    if theme is None:
        raise HTTPException(status_code=404, detail="theme not found")
    blueprint = blueprints.get_latest(theme_id)
    if blueprint is None:
        raise HTTPException(
            status_code=409, detail="no blueprint companies; generate one first"
        )
    return task_sse(
        theme_id=theme_id,
        kind="financials-research",
        label="Financials research",
        factory=lambda: research_financials_events(theme, blueprint.companies, repo, llm),
    )
