"""CE-6: factor compute + quant screener over the ingestion store.

Joins the latest (and prior) annual ``FinancialFact`` with the ``PriceBar`` window to compute a
descriptive factor set per ticker — valuation (PE/PB/PS), quality (ROE/margins), growth, size
(market cap), FCF yield, and price momentum/52-week range — then filters/ranks the universe by
ANY factor. All figures are computed from already-ingested, sourced data (no forecasting; this is
cross-sectional description, not advice). Factors with missing inputs stay null (never faked).
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from app.store.db import SessionLocal
from app.store.models import PriceBar
from app.store.screener import _OPS, _periods_for

# financial line items the factors need (latest + prior annual period)
_NEED = [
    "revenue", "net_income", "gross_profit", "shareholders_equity", "earnings_per_share",
    "outstanding_shares", "weighted_average_shares", "net_cash_flow_from_operations", "capital_expenditure",
]

# the descriptive factors this screener exposes (filter/sort fields)
FACTORS = ["price", "market_cap", "pe", "pb", "ps", "roe", "net_margin", "gross_margin",
           "revenue_growth", "fcf_yield", "return_window", "pct_from_high", "high_52w", "low_52w"]


def _safe_div(a, b):
    try:
        return a / b if (a is not None and b) else None
    except (TypeError, ZeroDivisionError):
        return None


def _price_window(db, market: str, days: int = 372) -> dict[str, dict]:
    """Per-ticker {first, last, high, low} daily close over the trailing window (one query)."""
    cutoff = date.today() - timedelta(days=days)
    rows = db.execute(
        select(PriceBar.ticker, PriceBar.bar_date, PriceBar.close).where(
            PriceBar.market == market.upper(), PriceBar.interval == "day",
            PriceBar.bar_date >= cutoff, PriceBar.close.isnot(None))
        .order_by(PriceBar.ticker, PriceBar.bar_date)
    ).all()
    out: dict[str, dict] = {}
    for tk, _bd, close in rows:
        slot = out.get(tk)
        if slot is None:
            out[tk] = {"first": close, "last": close, "high": close, "low": close}
        else:
            slot["last"] = close
            slot["high"] = max(slot["high"], close)
            slot["low"] = min(slot["low"], close)
    return out


def compute_factors(market: str, period: str = "annual") -> dict[str, dict]:
    """Compute the factor set for every ingested ticker in a market."""
    market = market.upper()
    with SessionLocal() as db:
        fin = _periods_for(db, _NEED, period, market, None)
        prices = _price_window(db, market)
    factors: dict[str, dict] = {}
    for ticker, periods in fin.items():
        v = periods[0]["_vals"]
        prior = periods[1]["_vals"] if len(periods) > 1 else {}
        shares = v.get("outstanding_shares") or v.get("weighted_average_shares")
        equity, revenue, ni = v.get("shareholders_equity"), v.get("revenue"), v.get("net_income")
        px = prices.get(ticker, {})
        price = px.get("last")
        mcap = price * shares if (price is not None and shares) else None
        ocf, capex = v.get("net_cash_flow_from_operations"), v.get("capital_expenditure")
        fcf = (ocf - abs(capex)) if (ocf is not None and capex is not None) else None
        f = {
            "ticker": ticker,
            "report_period": periods[0]["report_period"].isoformat(),
            "price": price,
            "market_cap": mcap,
            "pe": _safe_div(price, v.get("earnings_per_share")) if (v.get("earnings_per_share") or 0) > 0 else None,
            "pb": _safe_div(mcap, equity) if (equity or 0) > 0 else None,
            "ps": _safe_div(mcap, revenue) if (revenue or 0) > 0 else None,
            "roe": _safe_div(ni, equity),
            "net_margin": _safe_div(ni, revenue),
            "gross_margin": _safe_div(v.get("gross_profit"), revenue),
            "revenue_growth": (_safe_div(revenue, prior.get("revenue")) - 1) if (revenue and prior.get("revenue")) else None,
            "fcf_yield": _safe_div(fcf, mcap),
            "return_window": (_safe_div(px.get("last"), px.get("first")) - 1) if px.get("first") else None,
            "high_52w": px.get("high"),
            "low_52w": px.get("low"),
            "pct_from_high": (_safe_div(price, px.get("high")) - 1) if px.get("high") else None,
        }
        factors[ticker] = f
    return factors


def run_quant_screen(filters: list[dict], *, sort: str | None = None, order: str = "desc",
                     limit: int = 25, market: str = "US", period: str = "annual") -> dict:
    """Filter the universe by factor criteria, optionally rank by a factor, return the top rows."""
    factors = compute_factors(market, period)
    rows = list(factors.values())
    applied = []
    for fl in filters or []:
        field, op, val = fl.get("field"), fl.get("operator"), fl.get("value")
        if field not in FACTORS or op not in _OPS:
            continue
        applied.append({"field": field, "operator": op, "value": val})
        rows = [r for r in rows if r.get(field) is not None and _OPS[op](r[field], val)]
    if sort in FACTORS:
        rows = [r for r in rows if r.get(sort) is not None]
        rows.sort(key=lambda r: r[sort], reverse=(order != "asc"))
    else:
        rows.sort(key=lambda r: r["ticker"])
    return {"market": market.upper(), "factors": FACTORS, "applied_filters": applied,
            "sort": sort if sort in FACTORS else None, "order": order,
            "count": len(rows), "results": rows[:limit]}
