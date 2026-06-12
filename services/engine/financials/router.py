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
from services.engine.financials.research import (
    FINANCIALS_BATCH_SIZE,
    research_financials_events,
)
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
    tickers: Annotated[str | None, Query()] = None,
    batch_size: Annotated[int, Query(ge=1, le=20)] = FINANCIALS_BATCH_SIZE,
) -> StreamingResponse:
    """Deep Research blueprint companies' financials (revenue + cost buckets) and fill the
    store, as a live SSE stream. Pass ``tickers`` (comma-separated) to research only those
    companies (e.g. one row) instead of all. ``batch_size`` sets how many companies each
    sequential Deep Research call covers. Detached: finishes even if the tab closes."""
    theme = themes.get_theme(theme_id)
    if theme is None:
        raise HTTPException(status_code=404, detail="theme not found")
    blueprint = blueprints.get_latest(theme_id)
    if blueprint is None:
        raise HTTPException(
            status_code=409, detail="no blueprint companies; generate one first"
        )
    companies = blueprint.companies
    kind = "financials-research"
    # The "research ALL" run skips companies already on file; an explicit per-company
    # request re-fetches even if filled.
    skip_filled = True
    if tickers:
        wanted = {t.strip().upper() for t in tickers.split(",") if t.strip()}
        companies = [c for c in blueprint.companies if c.ticker.upper() in wanted]
        if not companies:
            raise HTTPException(status_code=404, detail="no matching blueprint companies")
        skip_filled = False
        # A distinct kind per ticker set so per-company runs don't dedupe with each other
        # (or with the "all" run) and each stays independently re-attachable.
        kind = "financials-research:" + ",".join(sorted(c.ticker for c in companies))
    return task_sse(
        theme_id=theme_id,
        kind=kind,
        label="Financials research",
        factory=lambda: research_financials_events(
            theme, companies, repo, llm, skip_filled=skip_filled, batch_size=batch_size
        ),
    )
