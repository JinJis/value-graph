"""Corporate actions — dividends + splits history (PH-DATA-3).

Provenance workflow for this source:
  · FETCH   — Yahoo Finance chart `events=div,split` (keyless, both US + KR via .KS/.KQ).
  · PROCESS — typed Dividend / Split records with their ex/effective date + amount/ratio.
  · STORE   — on-demand (point-in-time historical events; no ingestion store needed).
  · SHOW    — Yahoo has no per-event document, so the honest evidence shape is a **data card**:
              the exact records + source ("Yahoo Finance") + as_of. (KR could later upgrade to a
              DART dividend-disclosure highlight.)
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.deps import ApiKeyDep, MarketParam
from app.providers.registry import get_prices_provider
from app.symbols import Market, build_ref, normalize_ticker

router = APIRouter(tags=["Corporate Actions"])


class Dividend(BaseModel):
    ex_date: str
    amount: float


class Split(BaseModel):
    date: str
    ratio: str | None = None
    numerator: float | None = None
    denominator: float | None = None


class CorporateActionsResponse(BaseModel):
    ticker: str
    market: str
    currency: str | None = None
    dividends: list[Dividend]
    splits: list[Split]


@router.get(
    "/corporate-actions",
    response_model=CorporateActionsResponse,
    dependencies=[ApiKeyDep],
    summary="Dividends + splits history (Yahoo)",
    description="Historical dividends (ex-date + amount) and stock splits for a ticker. "
                "Descriptive data — sourced to Yahoo Finance with each event's date; no forecast.",
)
async def get_corporate_actions(
    ticker: str = Query(..., description="Ticker (US: AAPL; KR: 005930)."),
    years: int = Query(5, ge=1, le=30, description="Look-back window in years."),
    market: MarketParam = Market.US,
) -> CorporateActionsResponse:
    ref = build_ref(market, normalize_ticker(market, ticker))
    end = date.today()
    start = date(end.year - years, 1, 1)
    data = await get_prices_provider(market).corporate_actions(ref, start, end)
    return CorporateActionsResponse(
        ticker=ref.ticker, market=market.value, currency=data.get("currency"),
        dividends=data["dividends"], splits=data["splits"],
    )
