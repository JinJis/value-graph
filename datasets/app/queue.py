"""Procrastinate task queue — Postgres-backed, async. Replaces the in-process asyncio scheduler.

One `App` over the datasets Postgres DB; Procrastinate manages its own `procrastinate_*` tables
there (no Redis/RabbitMQ — the broker IS Postgres). Pipeline runs become durable jobs with retries +
a serialize-lock (replaces the old `backfill_running`/`news_ingest_running` mutex) + a queueing_lock
(dedup — never queue the same pipeline twice). The scheduler loop becomes per-pipeline `@app.periodic`
cron tasks. A separate `worker` process runs them; admin reads/controls jobs via `app.job_manager`.
"""

from __future__ import annotations

import logging

from procrastinate import App, PsycopgConnector, RetryStrategy

from app.config import settings
from app.pipelines import PIPELINE_BY_ID

logger = logging.getLogger(__name__)


def _conninfo(url: str) -> str:
    """SQLAlchemy uses ``postgresql+psycopg://``; Procrastinate/psycopg want a plain libpq URL."""
    return url.replace("postgresql+psycopg://", "postgresql://")


app = App(connector=PsycopgConnector(conninfo=_conninfo(settings.database_url)))


# One durable job = run one pipeline over one (market, tickers) set. queueing_lock dedups (only one
# pending job per pipeline+market); lock serializes execution per pipeline+market; retries on failure.
@app.task(
    name="run_pipeline",
    queue="ingest",
    retry=RetryStrategy(max_attempts=3, exponential_wait=30),
)
async def run_pipeline(market: str, tickers: list[str], pipeline_id: str) -> dict:
    p = PIPELINE_BY_ID.get(pipeline_id)
    if not p:
        return {"skipped": f"unknown pipeline {pipeline_id!r}"}
    if market not in p["markets"]:
        return {"skipped": f"{pipeline_id} not for market {market}"}
    await p["runner"](market, tickers)
    return {"ran": pipeline_id, "market": market, "tickers": len(tickers)}


async def defer_pipeline(market: str, tickers: list[str], pipeline_id: str) -> int | None:
    """Enqueue one pipeline run (deduped per pipeline+market). Returns the job id (or None if a
    job for that pipeline+market is already queued)."""
    job = run_pipeline.configure(
        lock=f"pipe:{pipeline_id}:{market}",
        queueing_lock=f"pipe:{pipeline_id}:{market}",
    )
    try:
        return await job.defer_async(market=market, tickers=tickers, pipeline_id=pipeline_id)
    except Exception as exc:  # noqa: BLE001 — AlreadyEnqueued (queueing_lock) → skip silently
        logger.info("defer_pipeline %s/%s skipped: %s", pipeline_id, market, exc)
        return None


# --- scheduling: per-pipeline cron sweeps (replaces the asyncio Scheduler loop) ----------------
# Each sweep resolves the configured universe and enqueues a run_pipeline job per market. Cadence
# lives in the cron (news ~hourly · prices ~daily · financials/corp_actions/filing_text ~weekly),
# which is what the old min_interval_seconds encoded. The worker runs these + processes the jobs.
async def _sweep(pipeline_id: str) -> None:
    from app.store.universes import resolve_universe

    for market, tickers in await resolve_universe(settings.scheduler_universe):
        if tickers:
            await defer_pipeline(market.value, tickers, pipeline_id)


@app.periodic(cron="0 * * * *")            # hourly
@app.task(name="sweep_news", queue="sweep", queueing_lock="sweep_news")
async def sweep_news(timestamp: int) -> None:
    await _sweep("news")


@app.periodic(cron="0 4 * * *")            # daily 04:00
@app.task(name="sweep_prices", queue="sweep", queueing_lock="sweep_prices")
async def sweep_prices(timestamp: int) -> None:
    await _sweep("prices")


@app.periodic(cron="0 3 * * 1")            # weekly Mon 03:00
@app.task(name="sweep_financials", queue="sweep", queueing_lock="sweep_financials")
async def sweep_financials(timestamp: int) -> None:
    await _sweep("financials")


@app.periodic(cron="30 3 * * 1")           # weekly Mon 03:30
@app.task(name="sweep_corp_actions", queue="sweep", queueing_lock="sweep_corp_actions")
async def sweep_corp_actions(timestamp: int) -> None:
    await _sweep("corp_actions")


@app.periodic(cron="0 5 * * 1")            # weekly Mon 05:00
@app.task(name="sweep_filing_text", queue="sweep", queueing_lock="sweep_filing_text")
async def sweep_filing_text(timestamp: int) -> None:
    await _sweep("filing_text")
