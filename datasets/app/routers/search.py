"""Cross-sectional search: screener + line-items (backed by the ingestion store).

Both query the store, so results cover whatever has been ingested. Run the
ingester first (`uv run python -m scripts.ingest US AAPL MSFT ...`).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from app.deps import ApiKeyDep, MarketParam
from app.models.generated import SearchFiltersRequest, SearchLineItemsRequest
from app.store.quant import FACTORS, run_quant_screen
from app.store.screener import run_line_items, run_screener
from app.symbols import Market

router = APIRouter(tags=["Financial Statements"])


class QuantFilter(BaseModel):
    field: str       # any factor (pe, pb, roe, market_cap, return_window, …)
    operator: str    # gt | lt | gte | lte | eq
    value: float


class QuantScreenRequest(BaseModel):
    filters: list[QuantFilter] = []
    sort: str | None = None      # rank by this factor
    order: str = "desc"          # desc | asc
    limit: int = 25


@router.post(
    "/financials/search/screener",
    dependencies=[ApiKeyDep],
    summary="Screen stocks by financial-statement criteria",
    description=(
        "Filter the ingested universe by line-item criteria (gt/lt/gte/lte/eq), or restrict "
        "to a ticker set with the `in` operator. Operates on the latest annual period per ticker."
    ),
)
async def search_screener(body: SearchFiltersRequest, market: MarketParam = Market.US) -> dict:
    filters = [{"field": f.field, "operator": f.operator.value, "value": f.value} for f in body.filters]
    results = await asyncio.to_thread(run_screener, filters, body.limit or 10, "annual", market.value)
    return {"search_results": results}


@router.post(
    "/quant/screen",
    dependencies=[ApiKeyDep],
    summary="퀀트 팩터 스크리너 — 밸류/퀄리티/성장/모멘텀/사이즈 팩터로 종목 필터·랭킹",
    description=(
        "Computes descriptive factors per ticker from the ingested store (FinancialFact + PriceBar) — "
        "valuation (pe/pb/ps), quality (roe/net_margin/gross_margin), growth (revenue_growth), size "
        "(market_cap), fcf_yield, and price momentum (return_window/pct_from_high/52w high·low) — then "
        "filters by any factor and ranks. Cross-sectional description over ingested data; no forecasts. "
        f"Factors: {', '.join(FACTORS)}."
    ),
)
async def quant_screen(body: QuantScreenRequest, market: MarketParam = Market.US) -> dict:
    filters = [{"field": f.field, "operator": f.operator, "value": f.value} for f in body.filters]
    return await asyncio.to_thread(
        run_quant_screen, filters, sort=body.sort, order=body.order,
        limit=body.limit or 25, market=market.value)


@router.post(
    "/financials/search/line-items",
    dependencies=[ApiKeyDep],
    summary="Fetch specific line items across tickers",
    description="Return the requested line items for each ticker (latest `limit` periods).",
)
async def search_line_items(body: SearchLineItemsRequest) -> dict:
    period = body.period.value if body.period else "ttm"
    results = await asyncio.to_thread(run_line_items, body.tickers, body.line_items, period, body.limit or 1)
    return {"search_results": results}
