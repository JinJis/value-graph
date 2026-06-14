"""Ingestion job log + backfill runner (PH-1).

Makes data ingestion *operable and visible*: every manual backfill or scheduled
refresh writes an ``IngestionJob`` row (status / rows / error / timing), and a
backfill can be triggered without shelling into the container. The admin ops
console reads these so an empty store is obvious (and fixable) rather than silent.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.store.bulk import bulk_load_kr, bulk_load_us
from app.store.db import SessionLocal
from app.store.models import IngestionJob


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def start_job(kind: str, market: str | None, spec: str | None) -> int:
    with SessionLocal() as db:
        job = IngestionJob(kind=kind, market=market, spec=spec, status="running", started_at=_now())
        db.add(job)
        db.commit()
        return job.id


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
                "status": j.status, "rows": j.rows, "error": j.error,
                "started_at": j.started_at.isoformat() if j.started_at else None,
                "ended_at": j.ended_at.isoformat() if j.ended_at else None,
            }
            for j in rows
        ]


async def run_backfill(market: str, tickers: list[str] | None, deep: bool, limit: int | None) -> dict:
    """Run a backfill and record it as an IngestionJob. Returns the job summary."""
    spec = (",".join(tickers) if tickers else "universe") + (" · deep" if deep else "")
    job_id = start_job("backfill", market, spec[:256])
    try:
        if market.upper() == "US":
            result = await bulk_load_us(tickers=tickers, limit=limit)
        elif market.upper() == "KR":
            if not tickers:
                raise ValueError("KR backfill requires explicit tickers.")
            result = await bulk_load_kr(tickers, limit=limit or 15)
        else:
            raise ValueError(f"Unknown market '{market}'.")
        # bulk_load_* returns {ticker: rows_written} (-1 on per-ticker failure)
        per = result if isinstance(result, dict) else {}
        rows = sum(v for v in per.values() if isinstance(v, int) and v > 0)
        failed = [t for t, v in per.items() if v == -1]
        finish_job(job_id, "success", rows=rows, error=(f"failed: {failed}" if failed else None))
        return {"job_id": job_id, "status": "success", "rows": rows, "per_ticker": per, "failed": failed}
    except Exception as exc:  # noqa: BLE001 — record the failure, don't crash the worker
        finish_job(job_id, "error", error=str(exc))
        return {"job_id": job_id, "status": "error", "error": str(exc)}
