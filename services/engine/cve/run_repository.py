"""[M3-ORCH-08] CVE run persistence: Protocol + in-memory (tests) + Postgres.

A "CVE run" is one end-to-end execution of the S0-S7 pipeline for a theme. Its
full intermediate state (claims, resolutions, per-edge estimates/reconciled/
scored/assessment, gap results) is persisted so nothing important lives only in
memory and a run is fully reconstructable. Runs are stored in the existing
`jobs` table with ``type='cve_run'`` (see migration 0008); the heavier versioned
graph persistence (Neo4j nodes/edges/claims) is M4-PERSIST-01.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from services.engine.db.config import DbSettings

CVE_RUN_JOB_TYPE = "cve_run"

# Run lifecycle states (mirrors the jobs.status convention).
RUNNING = "RUNNING"
DONE = "DONE"
FAILED = "FAILED"


class CveRunRecord(BaseModel):
    """One CVE pipeline run, including its full intermediate state once finished."""

    id: str
    theme_id: str
    trigger: str
    status: str
    state: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class CveRunRepository(Protocol):
    def start(self, theme_id: str, trigger: str) -> CveRunRecord: ...

    def finish(
        self, run_id: str, *, status: str, state: dict[str, Any]
    ) -> CveRunRecord | None: ...

    def get(self, run_id: str) -> CveRunRecord | None: ...

    def get_latest(self, theme_id: str) -> CveRunRecord | None: ...

    def list_runs(self, theme_id: str, *, limit: int = 20) -> list[CveRunRecord]: ...


class InMemoryCveRunRepository:
    def __init__(self) -> None:
        self._runs: dict[str, CveRunRecord] = {}

    def start(self, theme_id: str, trigger: str) -> CveRunRecord:
        now = datetime.now(UTC)
        record = CveRunRecord(
            id=str(uuid4()),
            theme_id=theme_id,
            trigger=trigger,
            status=RUNNING,
            state={},
            created_at=now,
            updated_at=now,
        )
        self._runs[record.id] = record
        return record

    def finish(self, run_id: str, *, status: str, state: dict[str, Any]) -> CveRunRecord | None:
        record = self._runs.get(run_id)
        if record is None:
            return None
        updated = record.model_copy(
            update={"status": status, "state": state, "updated_at": datetime.now(UTC)}
        )
        self._runs[run_id] = updated
        return updated

    def get(self, run_id: str) -> CveRunRecord | None:
        return self._runs.get(run_id)

    def get_latest(self, theme_id: str) -> CveRunRecord | None:
        runs = [r for r in self._runs.values() if r.theme_id == theme_id]
        return max(runs, default=None, key=lambda r: r.created_at)

    def list_runs(self, theme_id: str, *, limit: int = 20) -> list[CveRunRecord]:
        runs = [r for r in self._runs.values() if r.theme_id == theme_id]
        runs.sort(key=lambda r: r.created_at, reverse=True)
        return runs[:limit]


def _payload(trigger: str, state: dict[str, Any]) -> dict[str, Any]:
    return {"trigger": trigger, "state": state}


def _row_to_record(row: dict[str, Any]) -> CveRunRecord:
    payload = row["payload"] or {}
    return CveRunRecord(
        id=str(row["id"]),
        theme_id=str(row["theme_id"]),
        trigger=payload.get("trigger", ""),
        status=row["status"],
        state=payload.get("state", {}),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


_COLS = "id, status, payload, theme_id, created_at, updated_at"


class PostgresCveRunRepository:
    def __init__(self, settings: DbSettings) -> None:
        self._dsn = settings.database_url

    def _connect(self) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(self._dsn, row_factory=dict_row)

    def start(self, theme_id: str, trigger: str) -> CveRunRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO jobs (type, status, payload, theme_id) "
                f"VALUES (%s, %s, %s, %s) RETURNING {_COLS}",
                (CVE_RUN_JOB_TYPE, RUNNING, Jsonb(_payload(trigger, {})), theme_id),
            )
            row = cur.fetchone()
            assert row is not None
            return _row_to_record(row)

    def finish(self, run_id: str, *, status: str, state: dict[str, Any]) -> CveRunRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET status = %s, "
                "payload = jsonb_set(COALESCE(payload, '{}'::jsonb), '{state}', %s), "
                "updated_at = now() "
                f"WHERE id = %s AND type = %s RETURNING {_COLS}",
                (status, Jsonb(state), run_id, CVE_RUN_JOB_TYPE),
            )
            row = cur.fetchone()
            return _row_to_record(row) if row is not None else None

    def get(self, run_id: str) -> CveRunRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM jobs WHERE id = %s AND type = %s",
                (run_id, CVE_RUN_JOB_TYPE),
            )
            row = cur.fetchone()
            return _row_to_record(row) if row is not None else None

    def get_latest(self, theme_id: str) -> CveRunRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM jobs WHERE type = %s AND theme_id = %s "
                "ORDER BY created_at DESC LIMIT 1",
                (CVE_RUN_JOB_TYPE, theme_id),
            )
            row = cur.fetchone()
            return _row_to_record(row) if row is not None else None

    def list_runs(self, theme_id: str, *, limit: int = 20) -> list[CveRunRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM jobs WHERE type = %s AND theme_id = %s "
                "ORDER BY created_at DESC LIMIT %s",
                (CVE_RUN_JOB_TYPE, theme_id, limit),
            )
            return [_row_to_record(row) for row in cur.fetchall()]
