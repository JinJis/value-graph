"""Financial Metrics endpoints.

The real-time snapshot is backed by live providers (KR: pykrx fundamentals,
US: XBRL + EOD price). Historical metrics (`/financial-metrics`) derive ratios
across periods from the point-in-time ingestion store (PH-6).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query

from app.deps import ApiKeyDep, MarketParam
from app.models.generated import (
    FinancialMetricsHistoryResponse,
    FinancialMetricSnapshotResponse,
)
from app.providers.registry import get_metrics_provider
from app.store.metrics_history import metrics_history_models
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
    response_model=FinancialMetricsHistoryResponse,
    dependencies=[ApiKeyDep],
    summary="Historical derived financial metrics (ratios across periods)",
    description=(
        "Derives margins / returns / leverage / liquidity / YoY-growth ratios across periods from the "
        "point-in-time ingestion store. Store-backed: returns what's been ingested for the ticker (empty "
        "if it hasn't been backfilled). Gaps stay null — never fabricated."
    ),
)
async def get_financial_metrics(
    ticker: str = Query(..., description="The ticker symbol."),
    period: str = Query("annual", description="annual | quarterly | ttm"),
    limit: int = Query(8, ge=1, le=40, description="Number of recent periods."),
    market: MarketParam = Market.US,
) -> FinancialMetricsHistoryResponse:
    ref = build_ref(market, ticker)
    metrics = await asyncio.to_thread(metrics_history_models, market.value, ref.ticker, period, limit)
    return FinancialMetricsHistoryResponse(ticker=ref.ticker, period=period, metrics=metrics)
