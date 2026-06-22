"""Index-fund / ETF holdings (SEC N-PORT).

`?ticker=` returns a fund's portfolio constituents (US, real data from the latest N-PORT
filing). `?holding=` (which funds hold a security) is the reverse direction — it needs a
holdings index not built yet → 501. KR ETF holdings come via the KIS connector (KIS-ETF).
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.deps import ApiKeyDep, MarketParam
from app.errors import bad_request, not_implemented
from app.models.generated import IndexFundHoldingsResponse, IndexFundsTickersResponse
from app.providers.registry import get_fund_provider
from app.symbols import Market, build_ref, normalize_ticker

router = APIRouter(tags=["Index Funds"])

# Convenience universe — well-known US ETFs whose N-PORT holdings this resolves.
_ETFS = ["SPY", "IVV", "VOO", "VTI", "QQQ", "DIA", "IWM", "VEA", "VWO", "AGG",
         "BND", "VUG", "VTV", "XLK", "XLF", "XLE", "SCHD", "VIG", "VYM", "ARKK"]


@router.get(
    "/index-funds",
    response_model=IndexFundHoldingsResponse,
    summary="Index-fund / ETF holdings (SEC N-PORT)",
    description=(
        "`?ticker=` → the fund's constituents (US, from its latest N-PORT filing). "
        "`?holding=` (which funds hold a security) returns **HTTP 501** — needs a reverse "
        "holdings index. KR ETFs (KIS-ETF) not supported here yet."
    ),
    dependencies=[ApiKeyDep],
)
async def get_index_fund(
    ticker: str | None = Query(None, description="Fund/ETF ticker (e.g. SPY)."),
    holding: str | None = Query(None, description="Held security ticker (reverse; 501)."),
    limit: int = Query(50, ge=1, le=500),
    market: MarketParam = Market.US,
) -> IndexFundHoldingsResponse:
    if bool(ticker) == bool(holding):
        raise bad_request("Provide exactly one of `ticker` or `holding`.")
    if holding:
        raise not_implemented(
            "Reverse direction (which funds hold a security) needs a holdings index this build "
            "does not maintain yet. Use ?ticker= for a fund's constituents."
        )
    provider = get_fund_provider(market)
    norm = normalize_ticker(market, ticker)
    fund, holdings = await provider.holdings(build_ref(market, norm), limit)
    return IndexFundHoldingsResponse(ticker=norm, fund=fund, holdings=holdings)


@router.get("/index-funds/tickers", summary="Supported index-fund / ETF tickers")
async def index_fund_tickers(market: MarketParam = Market.US) -> IndexFundsTickersResponse:
    return IndexFundsTickersResponse(resource="index_funds", tickers=_ETFS)
