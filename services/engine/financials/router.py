"""Per-company financials endpoints — admin-entered complementary-side figures."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from services.engine.db.config import DbSettings
from services.engine.financials.models import FinancialsRecord, FinancialsUpsert
from services.engine.financials.repository import (
    FinancialsRepository,
    PostgresFinancialsRepository,
)

router = APIRouter(tags=["financials"])


def get_financials_repository() -> FinancialsRepository:
    return PostgresFinancialsRepository(DbSettings.from_env())


FinancialsRepoDep = Annotated[FinancialsRepository, Depends(get_financials_repository)]


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
