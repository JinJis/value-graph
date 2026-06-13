"""Financial Metrics endpoints.

The real-time snapshot is backed by live providers (KR: pykrx fundamentals,
US: XBRL + EOD price). Historical metrics (`/financial-metrics`) require
ratio derivation across periods and are scaffolded for a later iteration.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.deps import ApiKeyDep, MarketParam
from app.errors import NOT_IMPLEMENTED_TAG, not_implemented
from app.models.generated import FinancialMetricSnapshotResponse
from app.providers.registry import get_metrics_provider
from app.symbols import Market, build_ref

router = APIRouter(tags=["Financial Metrics"])


@router.get(
    "/financial-metrics/snapshot",
    response_model=FinancialMetricSnapshotResponse,
    dependencies=[ApiKeyDep],
)
async def get_financial_metrics_snapshot(
    ticker: str | None = Query(None),
    cik: str | None = Query(None),
    market: MarketParam = Market.US,
) -> FinancialMetricSnapshotResponse:
    ref = build_ref(market, ticker, cik)
    snap = await get_metrics_provider(market).metrics_snapshot(ref)
    return FinancialMetricSnapshotResponse(snapshot=snap)


@router.get(
    "/financial-metrics",
    tags=[NOT_IMPLEMENTED_TAG],
    summary="🚧 NOT IMPLEMENTED — GET /financial-metrics (historical)",
    description=(
        "**Not implemented yet** — historical metrics require ratio derivation across periods. "
        "Returns **HTTP 501**. Use `/financial-metrics/snapshot` for the latest values (implemented)."
    ),
    status_code=501,
    dependencies=[ApiKeyDep],
)
async def get_financial_metrics(
    period: str = Query(..., description="annual | quarterly | ttm"),
    ticker: str | None = Query(None),
    cik: str | None = Query(None),
    market: MarketParam = Market.US,
):
    raise not_implemented(
        "Historical financial-metrics is not implemented yet; use "
        "/financial-metrics/snapshot for the latest values."
    )
