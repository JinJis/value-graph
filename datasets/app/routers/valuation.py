"""CE-5: valuation-model endpoint (DCF / DDM / RIM).

A transparent, USER-input-driven calculator — NOT our forecast or price target. Base figures
are pulled from the company's real financials (sourced + as-of); the projection is the arithmetic
of the caller's assumptions. The response carries the full breakdown + a disclaimer label.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.deps import ApiKeyDep, MarketParam
from app.errors import bad_request, not_found
from app.store import valuation as V
from app.symbols import Market

router = APIRouter(tags=["Valuation"])


class ValuationResponse(BaseModel):
    resource: str = "valuation"
    model: str
    ticker: str
    market: str
    value_per_share: float | None = None
    assumptions: dict
    inputs: dict          # the sourced base figures used
    breakdown: dict       # the full math (projection rows + components)
    source: str | None = None
    as_of: str | None = None
    disclaimer: str = V.DISCLAIMER
    note: str | None = None


@router.get(
    "/valuation",
    response_model=ValuationResponse,
    dependencies=[ApiKeyDep],
    summary="밸류에이션 모델 (DCF/DDM/RIM) — 사용자 가정 기반 투명 계산 (예측·목표가 아님)",
    description=(
        "Computes an intrinsic value per share under the CALLER's assumptions, using the company's "
        "real financials as the base (FCF for DCF, dividend for DDM, book value+ROE for RIM). "
        "Transparent — returns the full projection breakdown + a disclaimer; it is NOT a forecast or "
        "price target. Override growth_rate/discount_rate/years/terminal_growth to explore scenarios."
    ),
)
async def valuation(
    ticker: str = Query(..., description="Company ticker (US) or KR 6-digit code."),
    model: str = Query("dcf", description="dcf | ddm | rim"),
    growth_rate: float = Query(0.08, description="Annual growth assumption (e.g. 0.08 = 8%)."),
    discount_rate: float = Query(0.10, description="Discount rate / cost of capital (e.g. 0.10)."),
    years: int = Query(5, ge=1, le=20, description="Explicit projection horizon (years)."),
    terminal_growth: float = Query(0.025, description="DCF terminal (perpetuity) growth."),
    dividend_per_share: float | None = Query(None, description="DDM only: current dividend/share (D0)."),
    market: MarketParam = Market.US,
) -> ValuationResponse:
    model = (model or "dcf").lower().strip()
    if model not in ("dcf", "ddm", "rim"):
        raise bad_request("model must be one of dcf, ddm, rim.")
    base = await V.base_inputs(market.value, ticker)
    assumptions = {"growth_rate": growth_rate, "discount_rate": discount_rate, "years": years,
                   "terminal_growth": terminal_growth}
    try:
        if model == "dcf":
            res = V.dcf(base["base_fcf"], base["shares"], base["net_debt"],
                        growth=growth_rate, discount=discount_rate, years=years,
                        terminal_growth=terminal_growth)
            inputs = {"base_fcf": base["base_fcf"], "shares": base["shares"], "net_debt": base["net_debt"]}
            need = "최근 연간 잉여현금흐름(영업CF−CapEx)과 발행주식수"
        elif model == "ddm":
            assumptions.pop("terminal_growth", None)
            assumptions["dividend_per_share"] = dividend_per_share
            res = V.ddm(dividend_per_share, growth=growth_rate, discount=discount_rate)
            inputs = {"dividend_per_share": dividend_per_share}
            need = "현재 주당배당금(dividend_per_share)"
        else:  # rim
            assumptions.pop("terminal_growth", None)
            res = V.rim(base["bvps"], base["roe"], growth=growth_rate, discount=discount_rate, years=years)
            inputs = {"bvps": base["bvps"], "roe": base["roe"], "equity": base["equity"], "shares": base["shares"]}
            need = "주당순자산(BVPS)과 ROE(순이익/자본)"
    except ValueError as exc:
        raise bad_request(str(exc))

    if res is None:
        return ValuationResponse(
            model=model, ticker=ticker.upper(), market=market.value, assumptions=assumptions,
            inputs=inputs, breakdown={}, source=None, as_of=base.get("as_of"),
            note=f"{need} 데이터가 부족해 계산할 수 없어요. (지어내지 않습니다.)")

    value = res.pop("value_per_share")
    src = "SEC EDGAR" if market.value == "US" else "OpenDART (FSS)"
    return ValuationResponse(
        model=model, ticker=ticker.upper(), market=market.value, value_per_share=value,
        assumptions=assumptions, inputs=inputs, breakdown=res,
        source=(src if model != "ddm" else "사용자 입력 (D0)"), as_of=base.get("as_of"))
