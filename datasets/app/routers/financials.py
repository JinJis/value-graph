"""Financial Statements endpoints (income statement, balance sheet, cash flow)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.deps import ApiKeyDep, MarketParam
from app.models.generated import (
    BalanceSheetResponse,
    CashFlowStatementResponse,
    Financials,
    FinancialsResponse,
    IncomeStatementResponse,
)
from app.providers.registry import get_financials_provider
from app.symbols import Market, build_ref

router = APIRouter(tags=["Financial Statements"])

_PERIODS = ["annual", "quarterly", "ttm"]


def _check_period(period: str) -> None:
    if period not in _PERIODS:
        from app.errors import bad_request

        raise bad_request(f"period must be one of {_PERIODS}.")


@router.get(
    "/financials/income-statements",
    response_model=IncomeStatementResponse,
    dependencies=[ApiKeyDep],
)
async def get_income_statements(
    period: str = Query(..., description="annual | quarterly | ttm"),
    ticker: str | None = Query(None),
    cik: str | None = Query(None),
    limit: int = Query(4, ge=1),
    market: MarketParam = Market.US,
) -> IncomeStatementResponse:
    _check_period(period)
    ref = build_ref(market, ticker, cik)
    rows = await get_financials_provider(market).income_statements(ref, period, limit)
    return IncomeStatementResponse(income_statements=rows)


@router.get(
    "/financials/balance-sheets",
    response_model=BalanceSheetResponse,
    dependencies=[ApiKeyDep],
)
async def get_balance_sheets(
    period: str = Query(..., description="annual | quarterly | ttm"),
    ticker: str | None = Query(None),
    cik: str | None = Query(None),
    limit: int = Query(4, ge=1),
    market: MarketParam = Market.US,
) -> BalanceSheetResponse:
    _check_period(period)
    ref = build_ref(market, ticker, cik)
    rows = await get_financials_provider(market).balance_sheets(ref, period, limit)
    return BalanceSheetResponse(balance_sheets=rows)


@router.get(
    "/financials/cash-flow-statements",
    response_model=CashFlowStatementResponse,
    dependencies=[ApiKeyDep],
)
async def get_cash_flow_statements(
    period: str = Query(..., description="annual | quarterly | ttm"),
    ticker: str | None = Query(None),
    cik: str | None = Query(None),
    limit: int = Query(4, ge=1),
    market: MarketParam = Market.US,
) -> CashFlowStatementResponse:
    _check_period(period)
    ref = build_ref(market, ticker, cik)
    rows = await get_financials_provider(market).cash_flow_statements(ref, period, limit)
    return CashFlowStatementResponse(cash_flow_statements=rows)


@router.get("/financials", response_model=FinancialsResponse, dependencies=[ApiKeyDep])
async def get_all_financial_statements(
    period: str = Query(..., description="annual | quarterly | ttm"),
    ticker: str | None = Query(None),
    cik: str | None = Query(None),
    limit: int = Query(4, ge=1),
    market: MarketParam = Market.US,
) -> FinancialsResponse:
    _check_period(period)
    ref = build_ref(market, ticker, cik)
    provider = get_financials_provider(market)
    return FinancialsResponse(
        financials=Financials(
            income_statements=await provider.income_statements(ref, period, limit),
            balance_sheets=await provider.balance_sheets(ref, period, limit),
            cash_flow_statements=await provider.cash_flow_statements(ref, period, limit),
        )
    )
