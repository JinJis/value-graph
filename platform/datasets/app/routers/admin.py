"""Admin / Ops: self-test, store stats, and scheduler monitor/control."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request

from app.deps import ApiKeyDep
from app.scheduler import scheduler
from app.selftest import run_selftest
from app.store.screener import store_stats

router = APIRouter(tags=["Admin / Ops"], prefix="/admin")


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
