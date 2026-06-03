"""[M7-TRIG-03] PostgresJobQueue against a live database (reuses the jobs table).

Gated behind VALUEGRAPH_DB_TESTS=1 (requires migrations applied).
"""

from __future__ import annotations

import os

import pytest

from services.engine.db.config import DbSettings
from services.engine.themes.models import ThemeCreate
from services.engine.themes.repository import PostgresThemeRepository
from services.pipeline.triggers.jobs import PostgresJobQueue
from services.pipeline.triggers.models import DONE, PENDING, CveJobCreate

pytestmark = pytest.mark.skipif(
    os.environ.get("VALUEGRAPH_DB_TESTS") != "1",
    reason="set VALUEGRAPH_DB_TESTS=1 (with Postgres up + migrations applied) to run",
)


def test_cve_job_enqueue_list_and_status() -> None:
    settings = DbSettings.from_env()
    theme = PostgresThemeRepository(settings).create_theme(ThemeCreate(name="TRIGGER DBTEST"))
    queue = PostgresJobQueue(settings)

    job = queue.enqueue(
        CveJobCreate(
            theme_id=theme.id,
            company="INTC",
            reason="new filing 2026-05-15",
            affected_edges=["ASML->INTC", "INTC->HPQ"],
        )
    )
    assert job.status == PENDING and job.company == "INTC"
    assert job.affected_edges == ["ASML->INTC", "INTC->HPQ"]

    pending = queue.list_pending(theme.id)
    assert any(j.id == job.id for j in pending)

    queue.set_status(job.id, DONE)
    assert queue.get(job.id).status == DONE  # type: ignore[union-attr]
    assert all(j.id != job.id for j in queue.list_pending(theme.id))  # drained
