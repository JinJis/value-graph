"""Cross-sectional search: screener + line-items (backed by the ingestion store).

Both query the store, so results cover whatever has been ingested. Run the
ingester first (`uv run python -m scripts.ingest US AAPL MSFT ...`).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from app.deps import ApiKeyDep, MarketParam
from app.models.generated import SearchFiltersRequest, SearchLineItemsRequest
from app.store.screener import run_line_items, run_screener
from app.symbols import Market

router = APIRouter(tags=["Financial Statements"])


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
    "/financials/search/line-items",
    dependencies=[ApiKeyDep],
    summary="Fetch specific line items across tickers",
    description="Return the requested line items for each ticker (latest `limit` periods).",
)
async def search_line_items(body: SearchLineItemsRequest) -> dict:
    period = body.period.value if body.period else "ttm"
    results = await asyncio.to_thread(run_line_items, body.tickers, body.line_items, period, body.limit or 1)
    return {"search_results": results}
