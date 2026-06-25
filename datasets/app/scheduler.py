"""Periodic ingestion scheduler with monitor/control hooks (PH-PIPE).

A single background asyncio task sweeps a configured UNIVERSE through a configured
set of data PIPELINES (financials · prices · corp_actions · news · …) on an
interval. It is observable (``status()``) and controllable (pause / resume /
run-now) via the /admin endpoints, and each pipeline run is recorded as an
``IngestionJob`` (so the admin shows path/coverage/errors/retries).

Disabled by default — enable via SCHEDULER_ENABLED=true or the admin "Resume"
button (the universe + pipeline set are pre-configured in settings).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.config import settings
from app.pipelines import PIPELINE_BY_ID, resolve_pipeline_ids, run_pipelines
from app.store.jobs import last_job_at
from app.store.universes import resolve_universe

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # matches how IngestionJob stamps time


class Scheduler:
    def __init__(self) -> None:
        self.enabled = settings.scheduler_enabled
        self.interval = settings.scheduler_interval_seconds
        # the universe is a SPEC (preset ids / explicit) resolved DYNAMICALLY each sweep, so
        # constituents stay fresh (e.g. S&P 500 / KOSPI 200 membership) — never a frozen list.
        self.universe_spec = settings.scheduler_universe
        self.last_universe: list[dict] = []  # [{market, count}] from the last resolve (for status)
        self.pipeline_ids = resolve_pipeline_ids(
            [p.strip() for p in settings.scheduler_pipelines.split(",") if p.strip()]
        )
        # cadence-aware: each sweep runs only the pipelines whose last run is older than their
        # `min_interval_seconds` (registry). So a 1h tick still re-pulls prices ~daily and
        # financials/corp_actions ~weekly — heavy history isn't re-fetched every sweep. A manual
        # run (force) ignores cadence and runs everything.
        self.cadence_aware = True
        self.last_skipped: dict[str, int] = {}  # pipeline_id → seconds until next due (last sweep)
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
            if (self.enabled or self._force) and self.universe_spec.strip():
                forced = self._force
                self._force = False
                await self._run_once(force=forced)
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    def _due_pipelines(self, ids: list[str], force: bool) -> list[str]:
        """Cadence filter: keep only pipelines whose last run is older than their
        `min_interval_seconds`. A forced (manual) run, or cadence_aware off, runs them all."""
        if force or not self.cadence_aware:
            self.last_skipped = {}
            return list(ids)
        now = _utcnow_naive()
        due: list[str] = []
        skipped: dict[str, int] = {}
        for pid in ids:
            p = PIPELINE_BY_ID.get(pid, {})
            mi = int(p.get("min_interval_seconds") or 0)
            if mi <= 0:
                due.append(pid)
                continue
            last = last_job_at(p.get("kind") or pid)
            age = (now - last).total_seconds() if last else None
            if age is None or age >= mi:
                due.append(pid)
            else:
                skipped[pid] = int(mi - age)  # seconds until next due
        self.last_skipped = skipped
        if skipped:
            logger.info("scheduler: skipping within-cadence pipelines %s", sorted(skipped))
        return due

    async def _run_once(self, force: bool = False) -> None:
        self.running, self.last_status = True, "running"
        summary: dict = {}
        try:
            universe = await resolve_universe(self.universe_spec)  # dynamic fetch each sweep
            self.last_universe = [{"market": m.value, "count": len(t)} for m, t in universe]
            ids = await asyncio.to_thread(self._due_pipelines, self.pipeline_ids, force)
            for market, tickers in universe:
                summary[market.value] = await run_pipelines(market.value, tickers, ids)
            # surfaced errors don't fail the sweep — they're recorded per pipeline/job
            had_error = any(
                isinstance(v, str) and v.startswith("error")
                for m in summary.values() for v in (m.values() if isinstance(m, dict) else [])
            )
            self.last_summary = summary
            self.last_status = "error" if had_error else "ok"
            self.last_error = None
        except Exception as exc:  # noqa: BLE001
            self.last_status, self.last_error, self.last_summary = "error", str(exc), summary
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

    @property
    def state(self) -> str:
        if self.running:
            return "running"
        return "enabled" if self.enabled else "paused"

    # --- monitor ---------------------------------------------------------
    def status(self) -> dict:
        return {
            "state": self.state,
            "enabled": self.enabled,
            "running": self.running,
            "interval_seconds": self.interval,
            "pipelines": self.pipeline_ids,
            "cadence_aware": self.cadence_aware,
            "cadence": {pid: PIPELINE_BY_ID.get(pid, {}).get("min_interval_seconds") or 0
                        for pid in self.pipeline_ids},
            "last_skipped": self.last_skipped,
            "universe_spec": self.universe_spec,
            "universe": self.last_universe,
            "universe_total": sum(u["count"] for u in self.last_universe),
            "run_count": self.run_count,
            "last_run_at": self.last_run_at,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "last_summary": self.last_summary,
        }


scheduler = Scheduler()
