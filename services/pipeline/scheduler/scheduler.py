"""[M7-SCHED-04] Scheduler: enqueue due-filing CVE jobs + drain the queue with retry/backoff.

A periodic tick (1) enqueues scheduled CVE jobs for companies whose next filing is due
(from the disclosure calendar, M7-CAL-01) and (2) drains PENDING jobs through a provided
executor, retrying transient failures with exponential backoff until ``max_attempts``.
Job execution writes upgraded data to Staging; the admin still re-publishes (no
auto-publish). Job status is observable in Studio via the jobs endpoint.

The executor is injected (CVE execution needs Gemini deps + documents), so this module
stays pure and testable.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from pydantic import BaseModel

from services.engine.calendar.repository import CalendarRepository
from services.pipeline.scheduler.backoff import backoff_delay
from services.pipeline.triggers.jobs import JobQueue
from services.pipeline.triggers.models import DONE, FAILED, PENDING, RUNNING, CveJob, CveJobCreate

JobExecutor = Callable[[CveJob], None]  # raises on (transient) failure


class DrainResult(BaseModel):
    ran: int = 0
    succeeded: int = 0
    retried: int = 0
    failed: int = 0


def enqueue_due(
    calendar_repo: CalendarRepository,
    job_queue: JobQueue,
    *,
    theme_id: str,
    tickers: list[str],
    today: datetime,
) -> list[CveJob]:
    """Enqueue a scheduled CVE job per due, tracked company (deduped vs pending)."""
    tracked = set(tickers)
    due = [e for e in calendar_repo.due_before(today.date()) if e.company_ticker in tracked]
    pending = {j.company for j in job_queue.list_pending(theme_id)}

    created: list[CveJob] = []
    for entry in due:
        if entry.company_ticker in pending:
            continue  # already queued; don't pile up
        created.append(
            job_queue.enqueue(
                CveJobCreate(
                    theme_id=theme_id,
                    company=entry.company_ticker,
                    trigger="scheduled",
                    reason=f"due filing {entry.next_filing_estimate}",
                )
            )
        )
    return created


def drain(
    job_queue: JobQueue,
    executor: JobExecutor,
    *,
    now: datetime,
    theme_id: str | None = None,
    max_attempts: int = 3,
    base_backoff_s: int = 60,
) -> DrainResult:
    """Run runnable PENDING jobs; on failure retry with backoff, else mark FAILED."""
    result = DrainResult()
    runnable = [
        j
        for j in job_queue.list_pending(theme_id)
        if j.next_retry_at is None or j.next_retry_at <= now
    ]
    for job in runnable:
        result.ran += 1
        job_queue.set_status(job.id, RUNNING)
        try:
            executor(job)
        except Exception:
            attempts = job.attempts + 1
            if attempts >= max_attempts:
                job_queue.reschedule(job.id, status=FAILED, attempts=attempts, next_retry_at=None)
                result.failed += 1
            else:
                retry_at = now + timedelta(seconds=backoff_delay(attempts, base_s=base_backoff_s))
                job_queue.reschedule(
                    job.id, status=PENDING, attempts=attempts, next_retry_at=retry_at
                )
                result.retried += 1
        else:
            job_queue.set_status(job.id, DONE)
            result.succeeded += 1
    return result
