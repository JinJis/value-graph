"""Admin / Ops: self-test, store stats, and scheduler monitor/control."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.deps import ApiKeyDep
from app.scheduler import scheduler
from app.selftest import run_selftest
from app.store.jobs import list_jobs, run_backfill
from app.store.screener import store_stats

router = APIRouter(tags=["Admin / Ops"], prefix="/admin")


class BackfillRequest(BaseModel):
    market: str = "US"
    tickers: list[str] | None = None  # required for KR; optional for US (universe)
    deep: bool = True
    limit: int | None = None


@router.get(
    "/selftest",
    dependencies=[ApiKeyDep],
    summary="▶ Run a live self-test of implemented endpoints",
    description=(
        "Drives a curated set of implemented endpoints (US + KR) through the real stack and "
        "returns pass / fail / skipped per check. `skipped` = an upstream key or IP is "
        "unavailable here (not a code failure). Click **Try it out → Execute** to run it."
    ),
)
async def selftest(request: Request) -> dict:
    return await run_selftest(request.app)


@router.get("/store/stats", dependencies=[ApiKeyDep], summary="Ingestion store stats")
async def store_statistics() -> dict:
    return await asyncio.to_thread(store_stats)


@router.get("/jobs", dependencies=[ApiKeyDep], summary="Recent ingestion jobs (backfill / scheduled)")
async def ingestion_jobs(limit: int = 25) -> dict:
    return {"jobs": await asyncio.to_thread(list_jobs, limit)}


@router.post(
    "/backfill",
    dependencies=[ApiKeyDep],
    summary="▶ Trigger a historical backfill (populates the ingestion store)",
    description=(
        "Runs in the background and records an `IngestionJob` (see `/admin/jobs`). "
        "US: `tickers` optional (omit for a broader load). KR: `tickers` required. "
        "Without this, the store is empty and the screener / historical endpoints return nothing."
    ),
)
async def backfill(body: BackfillRequest) -> dict:
    # fire-and-forget so the request returns immediately; progress is in /admin/jobs
    asyncio.create_task(run_backfill(body.market, body.tickers, body.deep, body.limit))
    return {"started": True, "market": body.market, "tickers": body.tickers, "see": "/admin/jobs"}


@router.get("/scheduler", dependencies=[ApiKeyDep], summary="Scheduler status (monitor)")
async def scheduler_status() -> dict:
    return scheduler.status()


@router.post("/scheduler/run", dependencies=[ApiKeyDep], summary="Trigger an ingestion run now")
async def scheduler_run() -> dict:
    scheduler.trigger()
    return {"triggered": True, **scheduler.status()}


@router.post("/scheduler/pause", dependencies=[ApiKeyDep], summary="Pause the scheduler")
async def scheduler_pause() -> dict:
    scheduler.pause()
    return scheduler.status()


@router.post("/scheduler/resume", dependencies=[ApiKeyDep], summary="Resume the scheduler")
async def scheduler_resume() -> dict:
    scheduler.resume()
    return scheduler.status()
