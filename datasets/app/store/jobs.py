"""Ingestion job log + backfill runner (PH-1).

Makes data ingestion *operable and visible*: every manual backfill or scheduled
refresh writes an ``IngestionJob`` row (status / rows / error / timing), and a
backfill can be triggered without shelling into the container. The admin ops
console reads these so an empty store is obvious (and fixable) rather than silent.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select

from app.store.bulk import bulk_load_kr, bulk_load_us
from app.store.db import SessionLocal
from app.store.models import IngestionJob
from app.store.universes import resolve_one


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def backfill_running() -> bool:
    """True if a backfill is already in flight — used to serialize runs (a poor
    man's single-worker queue; a real distributed queue is PH-11)."""
    with SessionLocal() as db:
        n = db.scalar(
            select(func.count()).select_from(IngestionJob)
            .where(IngestionJob.kind == "backfill", IngestionJob.status == "running")
        )
        return bool(n)


def start_job(kind: str, market: str | None, spec: str | None, total: int = 0) -> int:
    with SessionLocal() as db:
        job = IngestionJob(kind=kind, market=market, spec=spec, status="running",
                           total=total, done=0, started_at=_now())
        db.add(job)
        db.commit()
        return job.id


def update_progress(job_id: int, done: int) -> None:
    with SessionLocal() as db:
        job = db.get(IngestionJob, job_id)
        if job is not None:
            job.done = done
            db.commit()


def finish_job(job_id: int, status: str, rows: int = 0, error: str | None = None) -> None:
    with SessionLocal() as db:
        job = db.get(IngestionJob, job_id)
        if job is None:
            return
        job.status = status
        job.rows = rows
        job.error = (error or "")[:2000] or None
        job.ended_at = _now()
        db.commit()


def list_jobs(limit: int = 25) -> list[dict]:
    with SessionLocal() as db:
        rows = db.execute(
            select(IngestionJob).order_by(IngestionJob.started_at.desc()).limit(limit)
        ).scalars().all()
        return [
            {
                "id": j.id, "kind": j.kind, "market": j.market, "spec": j.spec,
                "status": j.status, "rows": j.rows, "total": j.total, "done": j.done,
                "error": j.error,
                "started_at": j.started_at.isoformat() if j.started_at else None,
                "ended_at": j.ended_at.isoformat() if j.ended_at else None,
            }
            for j in rows
        ]


async def run_backfill(
    market: str | None = None, tickers: list[str] | None = None, deep: bool = True,
    limit: int | None = None, preset: str | None = None,
) -> dict:
    """Run a backfill and record it as an IngestionJob (with live per-ticker progress).

    Either pass a ``preset`` id (resolved from universes) or an explicit ``market`` +
    ``tickers``. Serialized via ``backfill_running`` so runs don't pile up.
    """
    if preset:
        market, tickers = await resolve_one(preset)  # dynamic fetch (PH-PIPE)
        if not tickers:
            return {"status": "error", "error": f"Universe '{preset}' resolved to no tickers."}
        spec = f"universe:{preset}"
    else:
        spec = ",".join(tickers or []) or "(none)"
    if not market:
        return {"status": "error", "error": "market or preset required."}
    if not tickers:
        return {"status": "error", "error": "No tickers to backfill (US universe needs a preset or explicit tickers)."}
    if backfill_running():
        return {"status": "busy", "error": "A backfill is already running — wait for it to finish."}

    job_id = start_job("backfill", market, (spec + (" · deep" if deep else ""))[:256], total=len(tickers))
    progress = lambda done, total: update_progress(job_id, done)  # noqa: E731
    try:
        if market.upper() == "US":
            result = await bulk_load_us(tickers=tickers, limit=limit, on_progress=progress)
        elif market.upper() == "KR":
            result = await bulk_load_kr(tickers, limit=limit or 15, on_progress=progress)
        else:
            raise ValueError(f"Unknown market '{market}'.")
        per = result if isinstance(result, dict) else {}  # {ticker: rows} (-1 = per-ticker failure)
        rows = sum(v for v in per.values() if isinstance(v, int) and v > 0)
        failed = [t for t, v in per.items() if v == -1]
        finish_job(job_id, "success", rows=rows, error=(f"failed: {failed}" if failed else None))
        return {"job_id": job_id, "status": "success", "rows": rows, "per_ticker": per, "failed": failed}
    except Exception as exc:  # noqa: BLE001 — record the failure, don't crash the worker
        finish_job(job_id, "error", error=str(exc))
        return {"job_id": job_id, "status": "error", "error": str(exc)}
