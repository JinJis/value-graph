"""[M7-TRIG-03] CVE job queue: Protocol + in-memory + Postgres (reuses the jobs table).

A job is a scoped re-ingest + CVE work item (type='cve_job'). The scheduler (M7-SCHED-04)
drains PENDING jobs, runs CVE for the company, and writes the upgraded data to Staging —
the admin still re-publishes (no auto-publish).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from services.engine.db.config import DbSettings
from services.pipeline.triggers.models import PENDING, CveJob, CveJobCreate

CVE_JOB_TYPE = "cve_job"


class JobQueue(Protocol):
    def enqueue(self, data: CveJobCreate) -> CveJob: ...

    def list_pending(self, theme_id: str | None = None) -> list[CveJob]: ...

    def get(self, job_id: str) -> CveJob | None: ...

    def set_status(self, job_id: str, status: str) -> CveJob | None: ...


def _new_job(data: CveJobCreate, *, job_id: str, now: datetime, status: str = PENDING) -> CveJob:
    return CveJob(
        id=job_id,
        status=status,
        created_at=now,
        updated_at=now,
        **data.model_dump(),
    )


class InMemoryJobQueue:
    def __init__(self) -> None:
        self._jobs: dict[str, CveJob] = {}

    def enqueue(self, data: CveJobCreate) -> CveJob:
        job = _new_job(data, job_id=str(uuid4()), now=datetime.now(UTC))
        self._jobs[job.id] = job
        return job

    def list_pending(self, theme_id: str | None = None) -> list[CveJob]:
        jobs = [j for j in self._jobs.values() if j.status == PENDING]
        if theme_id is not None:
            jobs = [j for j in jobs if j.theme_id == theme_id]
        return sorted(jobs, key=lambda j: j.created_at)

    def get(self, job_id: str) -> CveJob | None:
        return self._jobs.get(job_id)

    def set_status(self, job_id: str, status: str) -> CveJob | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        updated = job.model_copy(update={"status": status, "updated_at": datetime.now(UTC)})
        self._jobs[job_id] = updated
        return updated


def _row_to_job(row: dict[str, Any]) -> CveJob:
    payload = row["payload"] or {}
    return CveJob(
        id=str(row["id"]),
        theme_id=str(row["theme_id"]),
        company=payload.get("company", ""),
        trigger=payload.get("trigger", "new_evidence"),
        reason=payload.get("reason"),
        affected_edges=payload.get("affected_edges", []),
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


_COLS = "id, status, payload, theme_id, created_at, updated_at"


class PostgresJobQueue:
    def __init__(self, settings: DbSettings) -> None:
        self._dsn = settings.database_url

    def _connect(self) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(self._dsn, row_factory=dict_row)

    def enqueue(self, data: CveJobCreate) -> CveJob:
        payload = {
            "company": data.company,
            "trigger": data.trigger,
            "reason": data.reason,
            "affected_edges": data.affected_edges,
        }
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO jobs (type, status, payload, theme_id) "
                f"VALUES (%s, %s, %s, %s) RETURNING {_COLS}",
                (CVE_JOB_TYPE, PENDING, Jsonb(payload), data.theme_id),
            )
            row = cur.fetchone()
            assert row is not None
            return _row_to_job(row)

    def list_pending(self, theme_id: str | None = None) -> list[CveJob]:
        clauses = ["type = %s", "status = %s"]
        params: list[Any] = [CVE_JOB_TYPE, PENDING]
        if theme_id is not None:
            clauses.append("theme_id = %s")
            params.append(theme_id)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM jobs WHERE {' AND '.join(clauses)} ORDER BY created_at",
                tuple(params),
            )
            return [_row_to_job(row) for row in cur.fetchall()]

    def get(self, job_id: str) -> CveJob | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM jobs WHERE id = %s AND type = %s",
                (job_id, CVE_JOB_TYPE),
            )
            row = cur.fetchone()
            return _row_to_job(row) if row is not None else None

    def set_status(self, job_id: str, status: str) -> CveJob | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET status = %s, updated_at = now() "
                f"WHERE id = %s AND type = %s RETURNING {_COLS}",
                (status, job_id, CVE_JOB_TYPE),
            )
            row = cur.fetchone()
            return _row_to_job(row) if row is not None else None
