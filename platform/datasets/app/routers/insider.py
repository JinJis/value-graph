"""Insider Trades endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.deps import ApiKeyDep, MarketParam
from app.models.generated import InsiderTradesResponse
from app.providers.registry import get_insider_provider
from app.symbols import Market, build_ref

router = APIRouter(tags=["Insider Trades"])


@router.get("/insider-trades", response_model=InsiderTradesResponse, dependencies=[ApiKeyDep])
async def get_insider_trades(
    ticker: str = Query(..., description="The ticker symbol."),
    limit: int = Query(10, ge=1, description="Max transactions (default 10)."),
    name: str | None = Query(None, description="Filter by insider name (substring)."),
    transaction_type: str | None = Query(None, description="Filter by transaction-type description."),
    market: MarketParam = Market.US,
) -> InsiderTradesResponse:
    ref = build_ref(market, ticker)
    trades = await get_insider_provider(market).insider_trades(ref, limit)
    if name:
        trades = [t for t in trades if t.name and name.lower() in t.name.lower()]
    if transaction_type:
        trades = [t for t in trades if t.transaction_type == transaction_type]
    return InsiderTradesResponse(insider_trades=trades)
