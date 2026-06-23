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
from app.providers.macro_indicators import (
    fetch_indicator,
    list_indicators,
    list_regions,
    region_panel,
)
from app.providers.registry import get_macro_provider
from app.symbols import Market

router = APIRouter(tags=["Macroeconomics"])


@router.get("/macro/indicators", dependencies=[ApiKeyDep],
            summary="Economic indicators (CPI, unemployment, GDP, …) — DBnomics, sourced")
async def get_macro_indicators(
    indicator: str | None = Query(None, description="Indicator slug (e.g. cpi); omit to list all."),
    region: str | None = Query(None, description="Filter the catalog by region (US/EA …) when listing."),
    group: str | None = Query(None, description="Filter the catalog by group/하위요인 (물가/고용/성장/금리) when listing."),
    limit: int = Query(24, ge=1, le=240, description="Recent observations to return."),
) -> dict:
    if not indicator:
        return {"resource": "economic_indicators", "regions": list_regions(),
                "indicators": list_indicators(region, group)}
    res = await fetch_indicator(indicator, limit)
    if not res:
        raise not_found(f"Unknown or unavailable indicator '{indicator}'. See GET /macro/indicators.")
    return res


@router.get("/macro/panel", dependencies=[ApiKeyDep],
            summary="국가경제 패널 — 한 지역의 핵심 지표 최신값·변화 스냅샷 (DBnomics, sourced)")
async def get_macro_panel(
    region: str = Query("US", description="국가/지역 (US, EA …). GET /macro/indicators의 regions 참고."),
) -> dict:
    res = await region_panel(region)
    if not res["indicators"]:
        raise not_found(f"No macro indicators available for region '{region}'.")
    return {"resource": "macro_panel", **res}


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
