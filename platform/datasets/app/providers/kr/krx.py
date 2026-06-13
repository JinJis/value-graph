"""KR prices + metrics via pykrx (free, no key; scrapes KRX/Naver, EOD).

pykrx is synchronous, so every call is offloaded with ``asyncio.to_thread`` to
keep the event loop free. Results are cached (TTL).
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from pykrx import stock

from app.cache import cache
from app.errors import not_found, upstream_error
from app.models.generated import FinancialMetricSnapshot, Price, PriceSnapshot
from app.symbols import SecurityRef

_FREQ = {"day": "d", "week": "d", "month": "m", "year": "y"}


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


async def _to_thread(fn, *args):
    try:
        return await asyncio.to_thread(fn, *args)
    except Exception as exc:  # pykrx raises bare exceptions / network errors
        raise upstream_error("pykrx", str(exc))


def _nearest_business_day() -> str:
    return stock.get_nearest_business_day_in_a_week()


class PyKrxProvider:
    async def prices(self, ref: SecurityRef, interval: str, start: date, end: date) -> list[Price]:
        freq = _FREQ.get(interval, "d")
        df = await _to_thread(stock.get_market_ohlcv, _ymd(start), _ymd(end), ref.ticker, freq)
        if df is None or df.empty:
            raise not_found(f"No KRX price data for '{ref.ticker}'.")
        out: list[Price] = []
        for idx, row in df.iterrows():
            out.append(
                Price(
                    time=idx.strftime("%Y-%m-%d"),
                    open=float(row["시가"]),
                    high=float(row["고가"]),
                    low=float(row["저가"]),
                    close=float(row["종가"]),
                    volume=int(row["거래량"]),
                )
            )
        return out

    async def snapshot(self, ref: SecurityRef) -> PriceSnapshot:
        end = await _to_thread(_nearest_business_day)
        start = (date.today() - timedelta(days=14)).strftime("%Y%m%d")
        df = await _to_thread(stock.get_market_ohlcv, start, end, ref.ticker, "d")
        if df is None or df.empty:
            raise not_found(f"No KRX snapshot for '{ref.ticker}'.")
        df = df[df["종가"] > 0]
        if df.empty:
            raise not_found(f"No KRX snapshot for '{ref.ticker}'.")
        last = df.iloc[-1]
        close = float(last["종가"])
        snap = PriceSnapshot(ticker=ref.ticker, price=close, time=df.index[-1].strftime("%Y-%m-%d"))
        if len(df) > 1:
            prev_close = float(df.iloc[-2]["종가"])
            if prev_close:
                snap.day_change = round(close - prev_close, 4)
                snap.day_change_percent = round((close - prev_close) / prev_close * 100, 4)
        return snap

    async def metrics_snapshot(self, ref: SecurityRef) -> FinancialMetricSnapshot:
        end = await _to_thread(_nearest_business_day)
        start = (date.today() - timedelta(days=14)).strftime("%Y%m%d")
        cap_df = await _to_thread(stock.get_market_cap, start, end, ref.ticker)
        fnd_df = await _to_thread(stock.get_market_fundamental, start, end, ref.ticker)
        if (cap_df is None or cap_df.empty) and (fnd_df is None or fnd_df.empty):
            raise not_found(f"No KRX metrics for '{ref.ticker}'.")
        snap = FinancialMetricSnapshot(ticker=ref.ticker)
        if cap_df is not None and not cap_df.empty:
            snap.market_cap = float(cap_df.iloc[-1]["시가총액"])
        if fnd_df is not None and not fnd_df.empty:
            last = fnd_df.iloc[-1]
            per, pbr = float(last["PER"]), float(last["PBR"])
            snap.price_to_earnings_ratio = round(per, 4) if per else None
            snap.price_to_book_ratio = round(pbr, 4) if pbr else None
        return snap
