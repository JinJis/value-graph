"""SEC / DART Filings endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.deps import ApiKeyDep, MarketParam
from app.models.generated import CiksResponse, FilingsResponse, TickersResponse
from app.providers.registry import get_company_provider, get_filings_provider
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


@router.get("/filings/tickers", response_model=TickersResponse)
async def get_filings_tickers(market: MarketParam = Market.US) -> TickersResponse:
    """Tickers in the filing universe (US: SEC company_tickers; KR: DART corp list)."""
    tickers = await get_company_provider(market).list_tickers()
    return TickersResponse(resource="filings", tickers=tickers)


@router.get("/filings/ciks", response_model=CiksResponse)
async def get_filings_ciks(market: MarketParam = Market.US) -> CiksResponse:
    """Filer ids in the filing universe (US: SEC CIK; KR: OpenDART corp_code)."""
    ciks = await get_company_provider(market).list_ciks()
    return CiksResponse(resource="filings", ciks=ciks)
