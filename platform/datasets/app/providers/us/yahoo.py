"""Keyless EOD prices via the Yahoo Finance chart API.

Works for both markets — US symbols are used as-is (``AAPL``); KR symbols are
tried with the ``.KS`` (KOSPI) then ``.KQ`` (KOSDAQ) suffix. Prices are delayed,
consistent with the default licensing posture.

    https://query1.finance.yahoo.com/v8/finance/chart/{symbol}
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.errors import not_found
from app.http import fetch_json
from app.models.generated import Price, PriceSnapshot
from app.symbols import Market, SecurityRef

_UA = {"User-Agent": "Mozilla/5.0 (compatible; ValueGraphDatasets/0.1)"}
_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
_INTERVALS = {"day": "1d", "week": "1wk", "month": "1mo", "year": "1mo"}


def _symbols(ref: SecurityRef) -> list[str]:
    if ref.market is Market.KR:
        return [f"{ref.ticker}.KS", f"{ref.ticker}.KQ"]
    return [ref.ticker.upper()]


def _epoch(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


async def _chart(symbol: str, params: dict) -> dict | None:
    data = await fetch_json("yahoo", f"{_BASE}/{symbol}", params=params, headers=_UA)
    results = (data.get("chart") or {}).get("result")  # type: ignore[union-attr]
    return results[0] if results else None


class YahooProvider:
    async def prices(self, ref: SecurityRef, interval: str, start: date, end: date) -> list[Price]:
        iv = _INTERVALS.get(interval, "1d")
        params = {"period1": _epoch(start), "period2": _epoch(end) + 86400, "interval": iv}
        result = None
        for symbol in _symbols(ref):
            result = await _chart(symbol, params)
            if result and result.get("timestamp"):
                break
        if not result or not result.get("timestamp"):
            raise not_found(f"No Yahoo price data for '{ref.ticker}'.")
        ts = result["timestamp"]
        q = (result.get("indicators", {}).get("quote") or [{}])[0]
        out: list[Price] = []
        for i, t in enumerate(ts):
            close = _at(q.get("close"), i)
            if close is None:
                continue
            vol = _at(q.get("volume"), i)
            out.append(
                Price(
                    time=datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d"),
                    open=_at(q.get("open"), i),
                    high=_at(q.get("high"), i),
                    low=_at(q.get("low"), i),
                    close=close,
                    volume=int(vol) if vol is not None else None,
                )
            )
        if not out:
            raise not_found(f"No Yahoo price data for '{ref.ticker}'.")
        return out

    async def snapshot(self, ref: SecurityRef) -> PriceSnapshot:
        params = {"range": "5d", "interval": "1d"}
        result = None
        for symbol in _symbols(ref):
            result = await _chart(symbol, params)
            if result:
                break
        if not result:
            raise not_found(f"No Yahoo snapshot for '{ref.ticker}'.")
        meta = result.get("meta", {})
        price = meta.get("regularMarketPrice")
        closes = [c for c in ((result.get("indicators", {}).get("quote") or [{}])[0].get("close") or []) if c is not None]
        if price is None and closes:
            price = closes[-1]
        if price is None:
            raise not_found(f"No Yahoo snapshot for '{ref.ticker}'.")
        snap = PriceSnapshot(ticker=ref.ticker, price=price)
        mt = meta.get("regularMarketTime")
        if mt:
            snap.time = datetime.fromtimestamp(mt, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            snap.time_milliseconds = mt * 1000
        prev = closes[-2] if len(closes) >= 2 else meta.get("chartPreviousClose")
        if prev:
            snap.day_change = round(price - prev, 4)
            snap.day_change_percent = round((price - prev) / prev * 100, 4)
        return snap


def _at(arr, i):
    if arr is None or i >= len(arr):
        return None
    return arr[i]
