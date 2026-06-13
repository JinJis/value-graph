"""US EOD prices from stooq (free, no key).

History: https://stooq.com/q/d/l/?s=aapl.us&i=d&d1=YYYYMMDD&d2=YYYYMMDD  -> CSV.
Prices are end-of-day (delayed), consistent with the default licensing posture.
"""

from __future__ import annotations

import csv
import io
from datetime import date

from app.errors import not_found, upstream_error
from app.http import fetch_text
from app.models.generated import Price, PriceSnapshot
from app.symbols import SecurityRef

_INTERVALS = {"day": "d", "week": "w", "month": "m", "year": "y"}


def _symbol(ref: SecurityRef) -> str:
    return f"{ref.ticker.lower()}.us"


def _parse_csv(text: str) -> list[dict]:
    if not text or text.lower().startswith("<"):
        return []
    reader = csv.DictReader(io.StringIO(text))
    return [row for row in reader if row.get("Date") and row.get("Close") not in (None, "", "N/D")]


def _to_price(row: dict) -> Price:
    def num(key: str) -> float | None:
        v = row.get(key)
        try:
            return float(v) if v not in (None, "", "N/D") else None
        except ValueError:
            return None

    vol = num("Volume")
    return Price(
        time=row["Date"],
        open=num("Open"),
        high=num("High"),
        low=num("Low"),
        close=num("Close"),
        volume=int(vol) if vol is not None else None,
    )


class StooqProvider:
    async def prices(self, ref: SecurityRef, interval: str, start: date, end: date) -> list[Price]:
        i = _INTERVALS.get(interval, "d")
        url = "https://stooq.com/q/d/l/"
        params = {
            "s": _symbol(ref),
            "i": i,
            "d1": start.strftime("%Y%m%d"),
            "d2": end.strftime("%Y%m%d"),
        }
        text = await fetch_text("stooq", url, params=params)
        rows = _parse_csv(text)
        if not rows:
            raise not_found(f"No stooq price data for '{ref.ticker}'.")
        return [_to_price(r) for r in rows]

    async def snapshot(self, ref: SecurityRef) -> PriceSnapshot:
        # Pull the most recent daily rows to derive the day change.
        url = "https://stooq.com/q/d/l/"
        params = {"s": _symbol(ref), "i": "d"}
        text = await fetch_text("stooq", url, params=params)
        rows = _parse_csv(text)
        if not rows:
            raise not_found(f"No stooq snapshot for '{ref.ticker}'.")
        last = rows[-1]
        prev = rows[-2] if len(rows) > 1 else None
        close = float(last["Close"])
        snap = PriceSnapshot(ticker=ref.ticker, price=close, time=last["Date"])
        if prev:
            prev_close = float(prev["Close"])
            snap.day_change = round(close - prev_close, 4)
            snap.day_change_percent = round((close - prev_close) / prev_close * 100, 4) if prev_close else None
        return snap
