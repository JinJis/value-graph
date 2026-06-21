"""Macroeconomics (interest rates) endpoints.

Market-scoped: ``market=US`` serves FRED (FED/ECB/BOE/BOJ), ``market=KR`` serves
the Bank of Korea (BOK) via ECOS.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query

from app.deps import ApiKeyDep, MarketParam
from app.errors import not_found
from app.models.generated import InterestRatesResponse
from app.providers.macro_indicators import fetch_indicator, list_indicators
from app.providers.registry import get_macro_provider
from app.symbols import Market

router = APIRouter(tags=["Macroeconomics"])


@router.get("/macro/indicators", dependencies=[ApiKeyDep],
            summary="Economic indicators (CPI, unemployment, GDP, …) — DBnomics, sourced")
async def get_macro_indicators(
    indicator: str | None = Query(None, description="Indicator slug (e.g. cpi); omit to list all."),
    limit: int = Query(24, ge=1, le=240, description="Recent observations to return."),
) -> dict:
    if not indicator:
        return {"resource": "economic_indicators", "indicators": list_indicators()}
    res = await fetch_indicator(indicator, limit)
    if not res:
        raise not_found(f"Unknown or unavailable indicator '{indicator}'. See GET /macro/indicators.")
    return res


@router.get("/macro/interest-rates", response_model=InterestRatesResponse, dependencies=[ApiKeyDep])
async def get_interest_rates(
    bank: str = Query(..., description="Central bank code (FED/ECB/BOE/BOJ for US, BOK for KR)."),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    market: MarketParam = Market.US,
) -> InterestRatesResponse:
    rates = await get_macro_provider(market).interest_rates(bank, start_date, end_date)
    return InterestRatesResponse(interest_rates=rates)


@router.get(
    "/macro/interest-rates/snapshot", response_model=InterestRatesResponse, dependencies=[ApiKeyDep]
)
async def get_interest_rates_snapshot(
    bank: str = Query(..., description="Central bank code."),
    market: MarketParam = Market.US,
) -> InterestRatesResponse:
    rates = await get_macro_provider(market).snapshot(bank)
    return InterestRatesResponse(interest_rates=rates)


@router.get("/macro/interest-rates/banks")
async def get_interest_rate_banks(market: MarketParam = Market.US) -> dict:
    return {"resource": "interest_rates", "banks": get_macro_provider(market).banks()}
