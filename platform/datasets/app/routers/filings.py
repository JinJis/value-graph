"""SEC / DART Filings endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.deps import ApiKeyDep, MarketParam
from app.models.generated import FilingsResponse
from app.providers.registry import get_filings_provider
from app.symbols import Market, build_ref

router = APIRouter(tags=["SEC Filings"])

_FILING_TYPES = {
    Market.US: ["10-K", "10-Q", "8-K", "20-F", "6-K"],
    Market.KR: ["사업보고서", "반기보고서", "분기보고서", "주요사항보고서"],
}


@router.get("/filings", response_model=FilingsResponse, dependencies=[ApiKeyDep])
async def get_filings(
    ticker: str | None = Query(None),
    cik: str | None = Query(None, description="US SEC CIK / KR OpenDART corp_code."),
    filing_type: list[str] | None = Query(None, description="Repeatable filter, e.g. filing_type=10-K."),
    limit: int = Query(10, ge=1),
    market: MarketParam = Market.US,
) -> FilingsResponse:
    ref = build_ref(market, ticker, cik)
    filings = await get_filings_provider(market).filings(ref, filing_type, limit)
    return FilingsResponse(filings=filings)


@router.get("/filings/types")
async def get_filing_types(market: MarketParam = Market.US) -> dict:
    return {"resource": "filings", "filing_types": _FILING_TYPES[market]}
