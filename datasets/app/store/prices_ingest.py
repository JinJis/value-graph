"""Prices + corporate-actions ingestion (PH-PIPE).

Periodically collects end-of-day OHLCV (``PriceBar``) and dividend/split events
(``CorporateAction``) for a universe and persists them — the two big "data we serve
but didn't store" gaps. Each run records an ``IngestionJob`` (kind ``prices`` /
``corp_actions``) so the admin console shows coverage + errors, and keeps going
per-ticker (one failure never sinks the run; bounded retries per ticker).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

from sqlalchemy import func, select

from app.providers.registry import get_prices_provider
from app.store.db import SessionLocal, init_db
from app.store.jobs import finish_job, start_job, update_progress
from app.store.models import CorporateAction, PriceBar
from app.symbols import Market, build_ref

logger = logging.getLogger(__name__)

_INTERVAL = "day"


def _to_date(v) -> date | None:
    try:
        return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None


# --- incremental: only fetch since the last stored row (a small overlap re-checks recent dates
#     for corrections / weekend gaps). First-ever pull falls back to the full history window. -----
def _last_bar_date(market: str, ticker: str) -> date | None:
    with SessionLocal() as db:
        return db.scalar(select(func.max(PriceBar.bar_date)).where(
            PriceBar.market == market, PriceBar.ticker == ticker, PriceBar.interval == _INTERVAL))


def _last_event_date(market: str, ticker: str) -> date | None:
    with SessionLocal() as db:
        return db.scalar(select(func.max(CorporateAction.event_date)).where(
            CorporateAction.market == market, CorporateAction.ticker == ticker))


def _incremental_start(last: date | None, full_start: date, overlap_days: int) -> date:
    """Start date for an incremental pull: last-stored − overlap, never before `full_start`.
    `last is None` (no prior data) → full backfill from `full_start`."""
    if last is None:
        return full_start
    return max(full_start, last - timedelta(days=overlap_days))


async def _retry(fn, retries: int):
    """Await ``fn`` up to ``retries``+1 times; return its result or raise the last error."""
    last = None
    for attempt in range(retries + 1):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < retries:
                await asyncio.sleep(0.5 * (attempt + 1))
    raise last  # type: ignore[misc]


# --- prices --------------------------------------------------------------
async def ingest_prices_ticker(market: Market, ticker: str, start: date, end: date, retries: int = 1) -> int:
    ref = build_ref(market, ticker)
    provider = get_prices_provider(market)
    bars = await _retry(lambda: provider.prices(ref, _INTERVAL, start, end), retries)
    rows = []
    for p in bars:
        d = p.model_dump() if hasattr(p, "model_dump") else dict(p)
        bd = _to_date(d.get("time"))
        if bd is None:
            continue
        rows.append({
            "market": market.value, "ticker": ref.ticker, "interval": _INTERVAL, "bar_date": bd,
            "open": _num(d.get("open")), "high": _num(d.get("high")), "low": _num(d.get("low")),
            "close": _num(d.get("close")), "volume": _num(d.get("volume")), "source": "yahoo",
        })

    def _write() -> int:
        with SessionLocal() as db:
            for r in rows:
                existing = db.execute(
                    select(PriceBar).where(
                        PriceBar.market == r["market"], PriceBar.ticker == r["ticker"],
                        PriceBar.interval == r["interval"], PriceBar.bar_date == r["bar_date"],
                    )
                ).scalar_one_or_none()
                if existing:
                    existing.open, existing.high, existing.low = r["open"], r["high"], r["low"]
                    existing.close, existing.volume = r["close"], r["volume"]
                else:
                    db.add(PriceBar(**r))
            db.commit()
        return len(rows)

    return await asyncio.to_thread(_write)


async def run_prices_ingest(market: str, tickers: list[str], years: int = 2, retries: int = 1,
                            overlap_days: int = 5) -> dict:
    """Collect daily OHLCV for ``tickers`` into ``PriceBar``; recorded as an IngestionJob.

    Incremental: each ticker is fetched only from its last stored bar (minus ``overlap_days`` to
    re-check recent corrections); a ticker with no data yet gets the full ``years``-year backfill."""
    init_db()
    mk = Market(market)
    end = date.today()
    full_start = date(end.year - years, end.month, end.day) if end.year - years > 0 else date(end.year - years, 1, 1)
    job = await asyncio.to_thread(start_job, "prices", market, f"prices · {len(tickers)} tickers (증분)", len(tickers))
    per: dict[str, int] = {}
    try:
        for i, t in enumerate(tickers, 1):
            try:
                nt = build_ref(mk, t).ticker
                last = await asyncio.to_thread(_last_bar_date, market, nt)
                start = _incremental_start(last, full_start, overlap_days)
                per[t] = await ingest_prices_ticker(mk, t, start, end, retries)
            except Exception as exc:  # noqa: BLE001
                per[t] = -1
                logger.warning("prices ingest failed %s:%s — %s", market, t, exc)
            await asyncio.to_thread(update_progress, job, i)
        rows = sum(v for v in per.values() if v > 0)
        failed = [t for t, v in per.items() if v == -1]
        await asyncio.to_thread(finish_job, job, "success", rows, (f"failed: {failed}" if failed else None))
        return {"status": "success", "rows": rows, "per_ticker": per, "failed": failed}
    except Exception as exc:  # noqa: BLE001
        await asyncio.to_thread(finish_job, job, "error", 0, str(exc))
        return {"status": "error", "error": str(exc)}


# --- corporate actions ---------------------------------------------------
async def ingest_corp_actions_ticker(market: Market, ticker: str, start: date, end: date, retries: int = 1) -> int:
    ref = build_ref(market, ticker)
    provider = get_prices_provider(market)
    data = await _retry(lambda: provider.corporate_actions(ref, start, end), retries)
    rows = []
    for d in (data.get("dividends") or []):
        ed = _to_date(d.get("ex_date"))
        if ed is not None:
            rows.append({"market": market.value, "ticker": ref.ticker, "kind": "dividend",
                         "event_date": ed, "amount": _num(d.get("amount")), "ratio": None, "source": "yahoo"})
    for s in (data.get("splits") or []):
        ed = _to_date(s.get("date"))
        if ed is not None:
            rows.append({"market": market.value, "ticker": ref.ticker, "kind": "split",
                         "event_date": ed, "amount": None, "ratio": s.get("ratio"), "source": "yahoo"})

    def _write() -> int:
        with SessionLocal() as db:
            for r in rows:
                existing = db.execute(
                    select(CorporateAction).where(
                        CorporateAction.market == r["market"], CorporateAction.ticker == r["ticker"],
                        CorporateAction.kind == r["kind"], CorporateAction.event_date == r["event_date"],
                    )
                ).scalar_one_or_none()
                if existing:
                    existing.amount, existing.ratio = r["amount"], r["ratio"]
                else:
                    db.add(CorporateAction(**r))
            db.commit()
        return len(rows)

    return await asyncio.to_thread(_write)


async def run_corp_actions_ingest(market: str, tickers: list[str], years: int = 10, retries: int = 1,
                                  overlap_days: int = 35) -> dict:
    """Collect dividends + splits for ``tickers`` into ``CorporateAction``; recorded as a job.

    Incremental: each ticker is fetched only from its last stored event (minus ``overlap_days``);
    a ticker with no events yet gets the full ``years``-year backfill."""
    init_db()
    mk = Market(market)
    end = date.today()
    full_start = date(end.year - years, 1, 1)
    job = await asyncio.to_thread(start_job, "corp_actions", market, f"corp_actions · {len(tickers)} tickers (증분)", len(tickers))
    per: dict[str, int] = {}
    try:
        for i, t in enumerate(tickers, 1):
            try:
                nt = build_ref(mk, t).ticker
                last = await asyncio.to_thread(_last_event_date, market, nt)
                start = _incremental_start(last, full_start, overlap_days)
                per[t] = await ingest_corp_actions_ticker(mk, t, start, end, retries)
            except Exception as exc:  # noqa: BLE001
                per[t] = -1
                logger.warning("corp-actions ingest failed %s:%s — %s", market, t, exc)
            await asyncio.to_thread(update_progress, job, i)
        rows = sum(v for v in per.values() if v > 0)
        failed = [t for t, v in per.items() if v == -1]
        await asyncio.to_thread(finish_job, job, "success", rows, (f"failed: {failed}" if failed else None))
        return {"status": "success", "rows": rows, "per_ticker": per, "failed": failed}
    except Exception as exc:  # noqa: BLE001
        await asyncio.to_thread(finish_job, job, "error", 0, str(exc))
        return {"status": "error", "error": str(exc)}


def price_coverage() -> dict:
    """Store coverage for prices + corporate actions (for the admin Data view)."""
    with SessionLocal() as db:
        bars = db.scalar(select(func.count()).select_from(PriceBar)) or 0
        price_tickers = db.scalar(select(func.count(func.distinct(PriceBar.ticker))).select_from(PriceBar)) or 0
        actions = db.scalar(select(func.count()).select_from(CorporateAction)) or 0
        return {"price_bars": bars, "price_tickers": price_tickers, "corporate_actions": actions}
