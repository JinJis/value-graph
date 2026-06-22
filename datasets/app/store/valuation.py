"""CE-5: transparent valuation models (DCF / DDM / RIM).

These are **user-input-driven calculators**, not our forecast or price target (CLAUDE §5 / the
guardrail still refuses the agent volunteering a target). The base figures (FCF, book value,
shares, net debt, ROE) come from the company's real financial statements — sourced + as-of — and
every projection is the arithmetic of the USER's own assumptions (growth, discount rate, years).
The output carries the full breakdown so the math is auditable, plus a disclaimer label.
"""

from __future__ import annotations

from app.providers.registry import get_financials_provider
from app.symbols import Market, build_ref

DISCLAIMER = ("입력 가정에 따른 계산값입니다 — 예측·목표가·매수의견이 아닙니다. "
              "가정(성장률·할인율 등)을 바꾸면 결과도 달라집니다.")


def _num(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


async def base_inputs(market: str, ticker: str) -> dict:
    """Pull the company's latest annual statements and derive the model base inputs (all
    sourced). Missing pieces stay None so a model degrades honestly rather than fabricating."""
    mkt = Market[market.upper()]
    ref = build_ref(mkt, ticker)
    prov = get_financials_provider(mkt)
    cf = await prov.cash_flow_statements(ref, "annual", 5)
    bs = await prov.balance_sheets(ref, "annual", 1)
    inc = await prov.income_statements(ref, "annual", 1)

    fcf_hist: list[float] = []
    for s in cf:  # newest-first
        ocf, capex = _num(s.net_cash_flow_from_operations), _num(s.capital_expenditure)
        if ocf is not None and capex is not None:
            fcf_hist.append(ocf - abs(capex))
    b = bs[0] if bs else None
    i = inc[0] if inc else None
    equity = _num(getattr(b, "shareholders_equity", None)) if b else None
    cash = _num(getattr(b, "cash_and_equivalents", None)) if b else None
    debt = _num(getattr(b, "total_debt", None)) if b else None
    shares = (_num(getattr(b, "outstanding_shares", None)) if b else None) \
        or (_num(getattr(i, "weighted_average_shares", None)) if i else None)
    net_income = _num(getattr(i, "net_income", None)) if i else None
    as_of = (str(getattr(b, "report_period", None)) if b else None) \
        or (str(getattr(cf[0], "report_period", None)) if cf else None)
    accession = (getattr(b, "accession_number", None) if b else None) \
        or (getattr(cf[0], "accession_number", None) if cf else None)
    return {
        "base_fcf": fcf_hist[0] if fcf_hist else None,
        "fcf_history": fcf_hist,
        "equity": equity,
        "net_debt": (debt or 0.0) - (cash or 0.0) if (debt is not None or cash is not None) else None,
        "shares": shares,
        "net_income": net_income,
        "bvps": (equity / shares) if (equity is not None and shares) else None,
        "roe": (net_income / equity) if (net_income is not None and equity) else None,
        "as_of": as_of,
        "accession": accession,
    }


def dcf(base_fcf: float | None, shares: float | None, net_debt: float | None, *,
        growth: float, discount: float, years: int, terminal_growth: float) -> dict | None:
    """Two-stage FCF DCF: project FCF `years` at `growth`, discount at `discount`, Gordon
    terminal at `terminal_growth` → EV → equity (− net debt) → per share."""
    if base_fcf is None or not shares or shares <= 0:
        return None
    if discount <= terminal_growth:
        raise ValueError("discount_rate must exceed terminal_growth.")
    rows, pv_sum, fcf = [], 0.0, float(base_fcf)
    for t in range(1, years + 1):
        fcf *= (1 + growth)
        pv = fcf / ((1 + discount) ** t)
        pv_sum += pv
        rows.append({"year": t, "fcf": fcf, "pv": pv})
    terminal_fcf = fcf * (1 + terminal_growth)
    tv = terminal_fcf / (discount - terminal_growth)
    pv_tv = tv / ((1 + discount) ** years)
    ev = pv_sum + pv_tv
    equity_value = ev - (net_debt or 0.0)
    return {"value_per_share": equity_value / shares, "enterprise_value": ev,
            "equity_value": equity_value, "pv_explicit": pv_sum, "pv_terminal": pv_tv,
            "terminal_value": tv, "rows": rows}


def ddm(d0: float | None, *, growth: float, discount: float) -> dict | None:
    """Gordon dividend discount model: value = D0·(1+g)/(r−g). D0 = current dividend/share."""
    if d0 is None:
        return None
    if discount <= growth:
        raise ValueError("discount_rate must exceed growth.")
    d1 = d0 * (1 + growth)
    return {"value_per_share": d1 / (discount - growth), "d1": d1, "d0": d0}


def rim(bvps: float | None, roe: float | None, *, discount: float, years: int, growth: float) -> dict | None:
    """Residual income model: value = BVPS + Σ PV(residual income) + PV(terminal RI), where
    RI_t = (ROE − r)·BVPS_{t-1} and BVPS compounds at `growth`."""
    if bvps is None or roe is None or not bvps:
        return None
    if discount <= growth:
        raise ValueError("discount_rate must exceed growth.")
    rows, pv_sum, bv = [], 0.0, float(bvps)
    last_ri = 0.0
    for t in range(1, years + 1):
        ri = (roe - discount) * bv
        pv = ri / ((1 + discount) ** t)
        pv_sum += pv
        rows.append({"year": t, "bvps": bv, "residual_income": ri, "pv": pv})
        last_ri = ri
        bv *= (1 + growth)
    terminal_ri = last_ri * (1 + growth)
    pv_terminal = (terminal_ri / (discount - growth)) / ((1 + discount) ** years)
    return {"value_per_share": bvps + pv_sum + pv_terminal, "bvps": bvps,
            "pv_residual": pv_sum, "pv_terminal": pv_terminal, "rows": rows}
