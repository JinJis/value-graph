"""Admin / Ops: self-test, store stats, and scheduler monitor/control."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.deps import ApiKeyDep
from app.scheduler import scheduler
from app.selftest import run_selftest
from app.store.jobs import backfill_running, list_jobs, run_backfill
from app.store.news_ingest import news_ingest_running, run_news_ingest
from app.store.screener import store_stats
from app.store.universes import list_presets

router = APIRouter(tags=["Admin / Ops"], prefix="/admin")


class BackfillRequest(BaseModel):
    preset: str | None = None  # a universe preset id (see /admin/universes); takes precedence
    market: str = "US"
    tickers: list[str] | None = None  # explicit tickers (required for US/KR without a preset)
    deep: bool = True
    limit: int | None = None


class NewsIngestRequest(BaseModel):
    market: str = "US"
    tickers: list[str] | None = None  # omit for broad market news
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


@router.get("/universes", dependencies=[ApiKeyDep], summary="Curated backfill universes (presets)")
async def universes() -> dict:
    return {"universes": list_presets()}


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
    # serialize: report busy synchronously so the caller knows it didn't start
    # (a single-worker queue; a real distributed queue is PH-11).
    if await asyncio.to_thread(backfill_running):
        return {"started": False, "busy": True, "detail": "A backfill is already running.", "see": "/admin/jobs"}
    # fire-and-forget so the request returns immediately; progress is in /admin/jobs
    asyncio.create_task(run_backfill(
        market=body.market, tickers=body.tickers, deep=body.deep, limit=body.limit, preset=body.preset,
    ))
    target = body.preset or f"{body.market}:{body.tickers}"
    return {"started": True, "target": target, "see": "/admin/jobs"}


@router.post(
    "/news/ingest",
    dependencies=[ApiKeyDep],
    summary="▶ Pull news into the RAG index (makes rag__search return real context)",
    description=(
        "Fetches Google News headlines for the given tickers (or broad market news) and "
        "indexes them into RAG as a global corpus. Runs in the background; records an "
        "`IngestionJob` (kind `news`) visible in `/admin/jobs`."
    ),
)
async def news_ingest(body: NewsIngestRequest) -> dict:
    if await asyncio.to_thread(news_ingest_running):
        return {"started": False, "busy": True, "detail": "A news ingestion is already running.", "see": "/admin/jobs"}
    asyncio.create_task(run_news_ingest(market=body.market, tickers=body.tickers, limit=body.limit))
    target = f"{body.market}:{body.tickers or '(market)'}"
    return {"started": True, "target": target, "see": "/admin/jobs"}


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
