"""Cross-sectional queries over the ingestion store: screener + line-items.

These are the queries that on-demand per-ticker fetching can't serve (they range
over the whole universe), which is exactly why the store exists.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select

from app.store.db import SessionLocal
from app.store.models import Company, FinancialFact


def store_stats() -> dict:
    """Counts for monitoring how much has been ingested."""
    with SessionLocal() as db:
        facts = db.scalar(select(func.count()).select_from(FinancialFact)) or 0
        companies = db.scalar(select(func.count()).select_from(Company)) or 0
        per_market = db.execute(
            select(
                FinancialFact.market,
                func.count(func.distinct(FinancialFact.ticker)),
                func.count(),
                func.min(FinancialFact.report_period),
                func.max(FinancialFact.report_period),
            ).group_by(FinancialFact.market)
        ).all()
    return {
        "total_facts": facts,
        "total_companies": companies,
        "by_market": [
            {
                "market": m,
                "tickers": tickers,
                "facts": n,
                "earliest_report_period": str(lo) if lo else None,
                "latest_report_period": str(hi) if hi else None,
            }
            for (m, tickers, n, lo, hi) in per_market
        ],
    }

_OPS = {
    "gt": lambda a, b: a > b,
    "lt": lambda a, b: a < b,
    "gte": lambda a, b: a >= b,
    "lte": lambda a, b: a <= b,
    "eq": lambda a, b: a == b,
}


def _periods_for(db, line_items: list[str], period: str, market: str | None, tickers: set[str] | None):
    """Return {ticker: [period_dict, ...]} newest-first, each dict = {report_period,
    currency, _vals:{line_item:value}}, keeping the latest value per (ticker,
    report_period, line_item) across restatements."""
    if not line_items:
        return {}
    q = select(FinancialFact).where(
        FinancialFact.line_item.in_(line_items), FinancialFact.period == period
    )
    if market:
        q = q.where(FinancialFact.market == market)
    if tickers:
        q = q.where(FinancialFact.ticker.in_(tickers))
    by_period: dict[tuple[str, date], dict] = {}
    chosen: dict[tuple[str, date, str], FinancialFact] = {}
    for f in db.execute(q).scalars():
        key = (f.ticker, f.report_period, f.line_item)
        prev = chosen.get(key)
        if prev is None or (f.filing_date or date.min) >= (prev.filing_date or date.min):
            chosen[key] = f
    for (ticker, rp, li), f in chosen.items():
        slot = by_period.setdefault((ticker, rp), {"report_period": rp, "currency": f.currency, "_vals": {}})
        slot["_vals"][li] = f.value
    out: dict[str, list[dict]] = {}
    for (ticker, _rp), slot in by_period.items():
        out.setdefault(ticker, []).append(slot)
    for ticker in out:
        out[ticker].sort(key=lambda d: d["report_period"], reverse=True)
    return out


def run_screener(filters: list[dict], limit: int, period: str = "annual", market: str | None = None) -> list[dict]:
    numeric = [f for f in filters if f["field"] not in ("ticker", "cik")]
    universe: set[str] | None = None
    for f in filters:
        if f["field"] in ("ticker", "cik") and f["operator"] == "in" and isinstance(f["value"], list):
            universe = {str(v).upper() for v in f["value"]}
    line_items = [f["field"] for f in numeric]
    with SessionLocal() as db:
        per = _periods_for(db, line_items, period, market, None)
    results: list[dict] = []
    for ticker, periods in per.items():
        if universe and ticker.upper() not in universe:
            continue
        latest = periods[0]
        vals = latest["_vals"]
        ok = True
        for f in numeric:
            v = vals.get(f["field"])
            if v is None or not _OPS[f["operator"]](v, f["value"]):
                ok = False
                break
        if ok:
            row = {"ticker": ticker, "report_period": latest["report_period"].isoformat(), "period": period, "currency": latest["currency"]}
            row.update(vals)
            results.append(row)
    results.sort(key=lambda r: r["ticker"])
    return results[:limit]


def run_line_items(tickers: list[str], line_items: list[str], period: str, limit: int) -> list[dict]:
    wanted = {t.upper() for t in tickers} | {t.zfill(6) for t in tickers if t.isdigit()}
    with SessionLocal() as db:
        per = _periods_for(db, line_items, period, None, wanted)
    results: list[dict] = []
    for raw in tickers:
        key = raw.upper() if not raw.isdigit() else raw.zfill(6)
        for slot in per.get(key, [])[:limit]:
            row = {"ticker": key, "report_period": slot["report_period"].isoformat(), "period": period, "currency": slot["currency"]}
            for li in line_items:
                row[li] = slot["_vals"].get(li)
            results.append(row)
    return results
