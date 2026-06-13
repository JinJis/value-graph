"""Market Data (prices) endpoints."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query

from app.deps import ApiKeyDep, MarketParam
from app.models.generated import (
    PriceSnapshotResponse,
    PricesResponse,
    TickersResponse,
)
from app.providers.registry import get_company_provider, get_prices_provider
from app.symbols import Market, build_ref

router = APIRouter(tags=["Market Data"])

_INTERVALS = ["day", "week", "month", "year"]


@router.get("/prices", response_model=PricesResponse, dependencies=[ApiKeyDep])
async def get_prices(
    ticker: str = Query(..., description="The stock ticker symbol."),
    interval: str = Query(..., description="day | week | month | year"),
    start_date: date = Query(..., description="Start date (YYYY-MM-DD)."),
    end_date: date = Query(..., description="End date (YYYY-MM-DD)."),
    market: MarketParam = Market.US,
) -> PricesResponse:
    if interval not in _INTERVALS:
        from app.errors import bad_request

        raise bad_request(f"interval must be one of {_INTERVALS}.")
    ref = build_ref(market, ticker)
    prices = await get_prices_provider(market).prices(ref, interval, start_date, end_date)
    return PricesResponse(ticker=ref.ticker, prices=prices)


@router.get("/prices/snapshot", response_model=PriceSnapshotResponse, dependencies=[ApiKeyDep])
async def get_price_snapshot(
    ticker: str = Query(..., description="The stock ticker symbol."),
    market: MarketParam = Market.US,
) -> PriceSnapshotResponse:
    ref = build_ref(market, ticker)
    snap = await get_prices_provider(market).snapshot(ref)
    return PriceSnapshotResponse(snapshot=snap)


@router.get("/prices/snapshot/tickers", response_model=TickersResponse)
async def get_price_snapshot_tickers(market: MarketParam = Market.US) -> TickersResponse:
    tickers = await get_company_provider(market).list_tickers()
    return TickersResponse(resource="prices", tickers=tickers)


@router.get("/prices/tickers", response_model=TickersResponse)
async def get_prices_tickers(market: MarketParam = Market.US) -> TickersResponse:
    tickers = await get_company_provider(market).list_tickers()
    return TickersResponse(resource="prices", tickers=tickers)
