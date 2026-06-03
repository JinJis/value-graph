"""[M7-SCHED-04] Read-only jobs endpoint — CVE job status, observable in Studio."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from services.engine.db.config import DbSettings
from services.pipeline.triggers.jobs import JobQueue, PostgresJobQueue
from services.pipeline.triggers.models import CveJob

router = APIRouter(tags=["jobs"])


def get_job_queue() -> JobQueue:
    return PostgresJobQueue(DbSettings.from_env())


JobQueueDep = Annotated[JobQueue, Depends(get_job_queue)]


@router.get("/jobs", response_model=list[CveJob])
def list_jobs(
    queue: JobQueueDep,
    theme_id: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
) -> list[CveJob]:
    """CVE jobs (newest first), optionally filtered by theme + status."""
    return queue.list_jobs(theme_id, status)
