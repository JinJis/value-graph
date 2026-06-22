"""CE-7: portfolio backtester over the ingested PriceBar store.

Computes the DESCRIPTIVE historical performance of a buy-and-hold allocation — what a given
weighting WOULD have returned over a past window (equity curve + total return, CAGR, volatility,
max drawdown), optionally vs a benchmark. Strictly past/descriptive: no forecast, no advice
(CLAUDE §5). Uses only ingested daily closes; if coverage is missing it says so (never fabricates).
"""

from __future__ import annotations

import math
import statistics
from datetime import date

from sqlalchemy import select

from app.store.db import SessionLocal
from app.store.models import PriceBar


def _series(db, market: str, ticker: str, start: date | None, end: date | None) -> dict[date, float]:
    q = select(PriceBar.bar_date, PriceBar.close).where(
        PriceBar.market == market.upper(), PriceBar.ticker == ticker.upper(),
        PriceBar.interval == "day", PriceBar.close.isnot(None))
    if start:
        q = q.where(PriceBar.bar_date >= start)
    if end:
        q = q.where(PriceBar.bar_date <= end)
    return {bd: c for bd, c in db.execute(q.order_by(PriceBar.bar_date)).all()}


def _metrics(dates: list[date], values: list[float]) -> dict:
    """Descriptive performance metrics for one value series."""
    if len(values) < 2:
        return {}
    rets = [values[i] / values[i - 1] - 1 for i in range(1, len(values)) if values[i - 1]]
    years = max((dates[-1] - dates[0]).days / 365.25, 1e-9)
    total = values[-1] / values[0] - 1
    peak, mdd = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    vol = statistics.pstdev(rets) * math.sqrt(252) if len(rets) > 1 else None
    return {
        "total_return": total,
        "cagr": (values[-1] / values[0]) ** (1 / years) - 1,
        "volatility": vol,
        "max_drawdown": mdd,
        "best_day": max(rets) if rets else None,
        "worst_day": min(rets) if rets else None,
    }


def run_backtest(market: str, holdings: list[dict], *, start: date | None = None, end: date | None = None,
                 initial: float = 10000.0, benchmark: str | None = None, curve_points: int = 120) -> dict:
    """Buy-and-hold backtest: allocate `initial` by weight at the first common date, hold the
    shares, value the book daily on ingested closes. Returns metrics + an equity curve."""
    # normalize weights
    valid = [(h["ticker"], float(h.get("weight") or 0)) for h in holdings if h.get("ticker")]
    wsum = sum(w for _, w in valid) or 1.0
    weights = {t.upper(): w / wsum for t, w in valid}
    if not weights:
        return {"error": "no holdings", "results": None}

    with SessionLocal() as db:
        series = {t: _series(db, market, t, start, end) for t in weights}
        bench_s = _series(db, market, benchmark, start, end) if benchmark else None

    missing = [t for t, s in series.items() if len(s) < 2]
    common = None
    for s in series.values():
        common = set(s) if common is None else (common & set(s))
    common = sorted(common or [])
    if len(common) < 2:
        return {"market": market.upper(), "results": None,
                "note": (f"백테스트할 가격 데이터가 부족합니다 (미보유/미수집: {', '.join(missing) or '공통 거래일 없음'}). "
                         "지어내지 않습니다 — 해당 종목을 먼저 수집(backfill)하세요.")}

    # buy-and-hold: shares fixed at the first common date
    d0 = common[0]
    shares = {t: (initial * weights[t]) / series[t][d0] for t in weights if series[t].get(d0)}
    values = [sum(shares[t] * series[t][d] for t in shares) for d in common]
    out = {"market": market.upper(), "start": d0.isoformat(), "end": common[-1].isoformat(),
           "initial": initial, "final": values[-1], "holdings": [{"ticker": t, "weight": round(weights[t], 4)} for t in weights],
           "metrics": _metrics(common, values)}
    # equity curve (downsampled to ~curve_points for a chartable artifact)
    step = max(1, len(common) // curve_points)
    out["curve"] = [{"date": common[i].isoformat(), "value": round(values[i], 2)} for i in range(0, len(common), step)]
    if out["curve"][-1]["date"] != common[-1].isoformat():
        out["curve"].append({"date": common[-1].isoformat(), "value": round(values[-1], 2)})
    if bench_s and len(bench_s) >= 2:
        bdates = [d for d in common if d in bench_s]
        if len(bdates) >= 2:
            bvals = [initial / bench_s[bdates[0]] * bench_s[d] for d in bdates]
            bstep = max(1, len(bdates) // curve_points)
            out["benchmark"] = {
                "ticker": benchmark.upper(), "metrics": _metrics(bdates, bvals),
                "curve": [{"date": bdates[i].isoformat(), "value": round(bvals[i], 2)}
                          for i in range(0, len(bdates), bstep)]}
    return out
