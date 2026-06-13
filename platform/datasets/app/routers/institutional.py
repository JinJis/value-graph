"""Institutional Holdings (13F) endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.deps import ApiKeyDep, MarketParam
from app.errors import bad_request
from app.models.generated import InstitutionalHoldingsResponse
from app.providers.registry import get_institutional_provider
from app.symbols import Market, build_ref, normalize_ticker

router = APIRouter(tags=["Institutional Holdings"])


@router.get(
    "/institutional-holdings",
    response_model=InstitutionalHoldingsResponse,
    summary="Get 13F institutional holdings (⚠️ filer_cik mode only)",
    description=(
        "**Partially implemented.** `?filer_cik=` returns a filer's latest 13F holdings (US, "
        "real data). `?ticker=` (which filers hold a security) returns **HTTP 501** — it needs a "
        "reverse CUSIP/holdings index not yet built. KR is not supported (501)."
    ),
    dependencies=[ApiKeyDep],
)
async def get_institutional_holdings(
    filer_cik: str | None = Query(None, description="10-digit SEC CIK of the institutional filer."),
    ticker: str | None = Query(None, description="Held security's ticker (mutually exclusive with filer_cik)."),
    limit: int = Query(10, ge=1, le=200),
    market: MarketParam = Market.US,
) -> InstitutionalHoldingsResponse:
    if bool(filer_cik) == bool(ticker):
        raise bad_request("Provide exactly one of `filer_cik` or `ticker`.")
    provider = get_institutional_provider(market)
    if filer_cik:
        holdings = await provider.by_filer(filer_cik, limit)
        return InstitutionalHoldingsResponse(filer_cik=filer_cik, institutional_holdings=holdings)
    norm = normalize_ticker(market, ticker)
    holdings = await provider.by_ticker(build_ref(market, norm), limit)
    return InstitutionalHoldingsResponse(ticker=norm, institutional_holdings=holdings)
