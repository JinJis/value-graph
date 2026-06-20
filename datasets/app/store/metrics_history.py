"""Historical financial-metrics (#21, PH-6) — ratios derived across periods.

Reads the point-in-time ingestion store (``FinancialFact``), pulls the line items a
ticker has per ``report_period``, and computes the ratios that those inputs support
(margins, returns, leverage, liquidity, YoY growth). It only sets a ratio when its
inputs exist — gaps stay null, never fabricated. Store-backed, so it works for
whatever has been backfilled (else returns an empty series).
"""

from __future__ import annotations

from sqlalchemy import select

from app.models.generated import FinancialMetricsResponse
from app.store.db import SessionLocal
from app.store.models import FinancialFact
from app.store.provenance import filing_link

# line items this module reads (statement field names as ingested)
_NEEDED = (
    "revenue", "gross_profit", "operating_income", "net_income", "interest_expense",
    "ebit", "earnings_per_share", "total_assets", "current_assets", "current_liabilities",
    "shareholders_equity", "current_debt", "non_current_debt", "free_cash_flow",
)


def _div(a, b):
    return (a / b) if (a is not None and b) else None


def _ratios(v: dict) -> dict:
    """Point-in-time ratios from one period's line items (None where inputs missing)."""
    rev = v.get("revenue")
    eq = v.get("shareholders_equity")
    assets = v.get("total_assets")
    debt = (v.get("current_debt") or 0) + (v.get("non_current_debt") or 0) or None
    return {
        "gross_margin": _div(v.get("gross_profit"), rev),
        "operating_margin": _div(v.get("operating_income"), rev),
        "net_margin": _div(v.get("net_income"), rev),
        "return_on_equity": _div(v.get("net_income"), eq),
        "return_on_assets": _div(v.get("net_income"), assets),
        "debt_to_equity": _div(debt, eq),
        "debt_to_assets": _div(debt, assets),
        "current_ratio": _div(v.get("current_assets"), v.get("current_liabilities")),
        "interest_coverage": _div(v.get("operating_income"), v.get("interest_expense")),
        "earnings_per_share": v.get("earnings_per_share"),
    }


def metrics_history(market: str, ticker: str, period: str = "annual", limit: int = 8) -> list[dict]:
    """Per-period derived metrics, newest first. YoY growth uses the adjacent older period."""
    with SessionLocal() as db:
        rows = db.execute(
            select(
                FinancialFact.report_period, FinancialFact.line_item,
                FinancialFact.value, FinancialFact.currency,
                FinancialFact.accession_number, FinancialFact.cik,
            ).where(
                FinancialFact.market == market.upper(),
                FinancialFact.ticker == ticker.upper(),
                FinancialFact.period == period,
                FinancialFact.line_item.in_(_NEEDED),
            )
        ).all()

    # collapse to {report_period: {line_item: value}} (keep one value per item/period)
    by_period: dict = {}
    ccy: dict = {}
    prov: dict = {}  # report_period -> (accession, cik) so each ratio links to its filing
    for rp, item, value, currency, accession, cik in rows:
        by_period.setdefault(rp, {})[item] = value
        if currency:
            ccy[rp] = currency
        if accession and rp not in prov:
            prov[rp] = (accession, cik)
    periods = sorted(by_period)  # ascending, so growth can look back one period
    out: list[dict] = []
    for i, rp in enumerate(periods):
        v = by_period[rp]
        m = _ratios(v)
        if i > 0:  # YoY growth vs the previous stored period
            prev = by_period[periods[i - 1]]
            m["revenue_growth"] = _pct_change(v.get("revenue"), prev.get("revenue"))
            m["earnings_growth"] = _pct_change(v.get("net_income"), prev.get("net_income"))
            m["operating_income_growth"] = _pct_change(v.get("operating_income"), prev.get("operating_income"))
        accession, cik = prov.get(rp, (None, None))
        row = {"report_period": rp, "currency": ccy.get(rp), **m}
        if accession:  # tie each period's ratios to the exact filing they came from
            row["accession_number"] = accession
            row["filing_url"] = filing_link(market, accession, cik)
        out.append(row)

    out.sort(key=lambda r: r["report_period"], reverse=True)  # newest first
    return out[:limit]


def _pct_change(cur, prev):
    if cur is None or not prev:
        return None
    return (cur - prev) / abs(prev)


def metrics_history_models(market: str, ticker: str, period: str, limit: int) -> list[FinancialMetricsResponse]:
    # period is carried by the wrapper (FinancialMetricsHistoryResponse), not per item,
    # to avoid coercing the str into the item model's enum.
    return [
        FinancialMetricsResponse(ticker=ticker.upper(), **{k: v for k, v in row.items() if v is not None})
        for row in metrics_history(market, ticker, period, limit)
    ]
