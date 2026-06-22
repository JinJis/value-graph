"""Admin / Ops: self-test, store stats, and scheduler monitor/control."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.deps import ApiKeyDep
from app.pipelines import list_pipelines, resolve_pipeline_ids, run_pipelines
from app.scheduler import scheduler
from app.selftest import run_selftest
from app.store.evidence_docs import run_build_evidence_docs
from app.store.filing_ingest import run_filing_text_ingest
from app.store.jobs import backfill_running, list_jobs, run_backfill
from app.store.news_ingest import news_ingest_running, run_news_ingest
from app.store.screener import store_stats
from app.store.universes import list_presets, resolve_one, resolve_universe

router = APIRouter(tags=["Admin / Ops"], prefix="/admin")


class BackfillRequest(BaseModel):
    preset: str | None = None  # a universe preset id (see /admin/universes); takes precedence
    market: str = "US"
    tickers: list[str] | None = None  # explicit tickers (required for US/KR without a preset)
    deep: bool = True
    limit: int | None = None


class PipelineRunRequest(BaseModel):
    """PH-PIPE unified backfill: run a SET of pipelines over a preset (or explicit market+tickers)."""
    preset: str | None = None       # universe preset id (see /admin/universes)
    market: str | None = None       # with `tickers`, an explicit universe instead of a preset
    tickers: list[str] | None = None
    pipelines: list[str] | None = None  # pipeline ids (see /admin/pipelines); omit → default set


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


@router.get("/pipelines", dependencies=[ApiKeyDep], summary="Data pipelines registry + latest run per pipeline")
async def pipelines() -> dict:
    """The PH-PIPE pipeline registry (what each collects, source, store) joined with the most
    recent IngestionJob per pipeline — so the admin can show path · schedule · status · coverage."""
    jobs = await asyncio.to_thread(list_jobs, 100)
    latest: dict[str, dict] = {}
    for j in jobs:  # jobs are newest-first → first seen per kind is the latest
        latest.setdefault(j["kind"], j)
    pipes = []
    for p in list_pipelines():
        pipes.append({**p, "latest": latest.get(p["kind"])})
    return {"pipelines": pipes, "scheduler": scheduler.status()}


@router.post(
    "/pipelines/run",
    dependencies=[ApiKeyDep],
    summary="▶ PH-PIPE: run a SET of pipelines over a universe (unified backfill)",
    description=(
        "Runs the selected `pipelines` (omit → default set) over a `preset` universe (or explicit "
        "`market`+`tickers`) in the background. Each pipeline records its own IngestionJob "
        "(see `/admin/jobs`); progress + errors + coverage show in the admin Pipelines view."
    ),
)
async def pipelines_run(body: PipelineRunRequest) -> dict:
    # resolve the universe → [(market, tickers)] (dynamic fetch for preset ids)
    if body.preset:
        groups = await resolve_universe(body.preset)
    elif body.market and body.tickers:
        from app.symbols import Market
        try:
            groups = [(Market(body.market.upper()), body.tickers)]
        except ValueError:
            return {"started": False, "detail": f"unknown market {body.market!r}"}
    else:
        return {"started": False, "detail": "preset or (market + tickers) required"}
    if not groups:
        return {"started": False, "detail": "empty universe"}
    ids = resolve_pipeline_ids(body.pipelines)

    async def _run_all() -> None:
        for market, tickers in groups:
            await run_pipelines(market.value, tickers, ids)

    asyncio.create_task(_run_all())
    total = sum(len(t) for _, t in groups)
    return {"started": True, "pipelines": ids,
            "universe": [{"market": m.value, "count": len(t)} for m, t in groups],
            "tickers_total": total, "see": "/admin/jobs"}


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


class EvidenceDocsRequest(BaseModel):
    preset: str | None = None  # a universe preset id (US); takes precedence
    market: str = "US"
    tickers: list[str] | None = None  # explicit tickers (watchlist-scoped)


@router.post(
    "/evidence-docs",
    dependencies=[ApiKeyDep],
    summary="▶ PH-PROV3: cache filings as PDFs for on-demand evidence (US + KR)",
    description=(
        "Downloads each ticker's recent filings and stores each as a PDF-normalized "
        "`EvidenceDoc` (US iXBRL HTML / KR DART markup → PDF). At query time PyMuPDF "
        "highlights whatever a figure cited — coverage is the whole document, not a fixed "
        "concept list. Runs in the background; progress in `/admin/jobs`."
    ),
)
async def evidence_docs(body: EvidenceDocsRequest) -> dict:
    market, tickers = body.market, body.tickers
    if body.preset:
        market, tickers = await resolve_one(body.preset)  # dynamic fetch (PH-PIPE)
        if not tickers:
            return {"started": False, "detail": f"universe {body.preset!r} resolved to no tickers"}
    if market not in ("US", "KR"):
        return {"started": False, "detail": "US + KR only", "market": market}
    if not tickers:
        return {"started": False, "detail": "tickers required"}
    asyncio.create_task(run_build_evidence_docs(market, tickers))
    return {"started": True, "target": f"{market}:{tickers}", "see": "/admin/jobs"}


@router.post(
    "/filings/ingest",
    dependencies=[ApiKeyDep],
    summary="▶ PH-PROV3e: index filing PDF text into RAG (full-text search + passage evidence)",
    description=(
        "Caches each ticker's filings as PDFs (if needed) and indexes their page text into RAG, "
        "so `rag__search` returns real filing passages (MD&A, notes, any line) and `/evidence` can "
        "highlight the cited passage. Global corpus; runs in the background, progress in `/admin/jobs`."
    ),
)
async def filings_ingest(body: EvidenceDocsRequest) -> dict:
    market, tickers = body.market, body.tickers
    if body.preset:
        market, tickers = await resolve_one(body.preset)  # dynamic fetch (PH-PIPE)
        if not tickers:
            return {"started": False, "detail": f"universe {body.preset!r} resolved to no tickers"}
    if market not in ("US", "KR"):
        return {"started": False, "detail": "US + KR only", "market": market}
    if not tickers:
        return {"started": False, "detail": "tickers required"}
    asyncio.create_task(run_filing_text_ingest(market, tickers))
    return {"started": True, "target": f"{market}:{tickers}", "see": "/admin/jobs"}


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
