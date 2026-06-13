"""Periodic ingestion scheduler with monitor/control hooks.

A single background asyncio task refreshes the store for a configured universe on
an interval. It is observable (``status()``) and controllable (pause / resume /
run-now) via the /admin endpoints. Disabled by default — set SCHEDULER_ENABLED
and SCHEDULER_UNIVERSE to turn it on.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.config import settings
from app.store.ingest import ingest_universe
from app.symbols import Market


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_universe(spec: str) -> list[tuple[Market, list[str]]]:
    """'US:AAPL,MSFT;KR:005930' -> [(US, [AAPL, MSFT]), (KR, [005930])]."""
    out: list[tuple[Market, list[str]]] = []
    for group in spec.split(";"):
        group = group.strip()
        if not group or ":" not in group:
            continue
        mkt, tickers = group.split(":", 1)
        syms = [t.strip() for t in tickers.split(",") if t.strip()]
        if syms:
            out.append((Market(mkt.strip().upper()), syms))
    return out


class Scheduler:
    def __init__(self) -> None:
        self.enabled = settings.scheduler_enabled
        self.interval = settings.scheduler_interval_seconds
        self.universe = parse_universe(settings.scheduler_universe)
        self.deep = settings.scheduler_deep
        self.run_count = 0
        self.last_run_at: str | None = None
        self.last_status = "idle"  # idle | running | ok | error
        self.last_summary: dict | None = None
        self.last_error: str | None = None
        self.running = False
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._force = False
        self._stop = False

    # --- lifecycle -------------------------------------------------------
    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop = True
        self._wake.set()
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        while not self._stop:
            if (self.enabled or self._force) and self.universe:
                self._force = False
                await self._run_once()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def _run_once(self) -> None:
        self.running, self.last_status = True, "running"
        try:
            summary: dict = {}
            if self.deep:
                from app.store.bulk import bulk_load_kr, bulk_load_us

                for market, tickers in self.universe:
                    summary[market.value] = await (
                        bulk_load_us(tickers) if market is Market.US else bulk_load_kr(tickers)
                    )
            else:
                for market, tickers in self.universe:
                    summary[market.value] = await ingest_universe(market, tickers)
            self.last_summary, self.last_status, self.last_error = summary, "ok", None
        except Exception as exc:
            self.last_status, self.last_error = "error", str(exc)
        finally:
            self.running = False
            self.run_count += 1
            self.last_run_at = _now()

    # --- control ---------------------------------------------------------
    def trigger(self) -> None:
        self._force = True
        self._wake.set()

    def pause(self) -> None:
        self.enabled = False

    def resume(self) -> None:
        self.enabled = True
        self._wake.set()

    # --- monitor ---------------------------------------------------------
    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "deep": self.deep,
            "running": self.running,
            "interval_seconds": self.interval,
            "universe": [{"market": m.value, "tickers": t} for m, t in self.universe],
            "run_count": self.run_count,
            "last_run_at": self.last_run_at,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "last_summary": self.last_summary,
        }


scheduler = Scheduler()
