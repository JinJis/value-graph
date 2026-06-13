"""Company Information endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.deps import ApiKeyDep, MarketParam
from app.models.generated import CompanyFactsResponse, TickersResponse
from app.providers.registry import get_company_provider
from app.symbols import Market, build_ref

router = APIRouter(tags=["Company Information"])


@router.get("/company/facts", response_model=CompanyFactsResponse, dependencies=[ApiKeyDep])
async def get_company_facts(
    market: MarketParam = Market.US,
    ticker: str | None = Query(None, description="The ticker symbol."),
    cik: str | None = Query(None, description="US SEC CIK / KR OpenDART corp_code."),
) -> CompanyFactsResponse:
    ref = build_ref(market, ticker, cik)
    facts = await get_company_provider(market).company_facts(ref)
    return CompanyFactsResponse(company_facts=facts)


@router.get("/company/facts/tickers", response_model=TickersResponse)
async def get_company_facts_tickers(market: MarketParam = Market.US) -> TickersResponse:
    tickers = await get_company_provider(market).list_tickers()
    return TickersResponse(resource="company_facts", tickers=tickers)
