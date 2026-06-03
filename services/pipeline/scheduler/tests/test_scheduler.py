"""[M7-SCHED-04] Scheduler: due-filing enqueue, drain with retry/backoff, jobs endpoint."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi.testclient import TestClient

from services.engine.calendar.models import CalendarUpsert
from services.engine.calendar.repository import InMemoryCalendarRepository
from services.engine.jobs.router import get_job_queue
from services.engine.main import app
from services.pipeline.scheduler.backoff import backoff_delay
from services.pipeline.scheduler.scheduler import drain, enqueue_due
from services.pipeline.triggers.jobs import InMemoryJobQueue
from services.pipeline.triggers.models import DONE, FAILED, PENDING, RUNNING, CveJob

NOW = datetime(2026, 6, 1, tzinfo=UTC)


def test_backoff_is_exponential_and_capped() -> None:
    assert backoff_delay(1, base_s=60) == 60
    assert backoff_delay(2, base_s=60) == 120
    assert backoff_delay(3, base_s=60) == 240
    assert backoff_delay(10, base_s=60, max_s=300) == 300  # capped


def test_enqueue_due_creates_scheduled_jobs_deduped() -> None:
    cal = InMemoryCalendarRepository()
    cal.upsert(CalendarUpsert(company_ticker="INTC", next_filing_estimate=date(2026, 5, 1)))
    cal.upsert(CalendarUpsert(company_ticker="HPQ", next_filing_estimate=date(2026, 9, 1)))
    queue = InMemoryJobQueue()

    created = enqueue_due(cal, queue, theme_id="t1", tickers=["INTC", "HPQ"], today=NOW)
    assert [j.company for j in created] == ["INTC"]  # only the overdue one
    assert created[0].trigger == "scheduled"

    # Re-tick: INTC already has a pending job -> no duplicate.
    again = enqueue_due(cal, queue, theme_id="t1", tickers=["INTC", "HPQ"], today=NOW)
    assert again == []


def test_drain_succeeds_and_marks_done() -> None:
    queue = InMemoryJobQueue()
    cal = InMemoryCalendarRepository()
    cal.upsert(CalendarUpsert(company_ticker="INTC", next_filing_estimate=date(2026, 5, 1)))
    enqueue_due(cal, queue, theme_id="t1", tickers=["INTC"], today=NOW)

    result = drain(queue, lambda job: None, now=NOW)
    assert result.ran == 1 and result.succeeded == 1
    assert queue.list_pending() == []
    assert queue.list_jobs(status=DONE)[0].company == "INTC"


def test_drain_retries_with_backoff_then_fails() -> None:
    queue = InMemoryJobQueue()
    cal = InMemoryCalendarRepository()
    cal.upsert(CalendarUpsert(company_ticker="INTC", next_filing_estimate=date(2026, 5, 1)))
    enqueue_due(cal, queue, theme_id="t1", tickers=["INTC"], today=NOW)

    def boom(job: CveJob) -> None:
        raise RuntimeError("transient")

    # Attempt 1: fails -> retried, scheduled in the future (not runnable at NOW).
    r1 = drain(queue, boom, now=NOW, max_attempts=2)
    assert r1.retried == 1 and r1.failed == 0
    job = queue.list_pending()[0]
    assert job.status == PENDING and job.attempts == 1 and job.next_retry_at is not None
    assert drain(queue, boom, now=NOW).ran == 0  # backoff not elapsed yet

    # Attempt 2 (after backoff): fails again -> exhausted -> FAILED.
    later = job.next_retry_at
    r2 = drain(queue, boom, now=later, max_attempts=2)
    assert r2.failed == 1
    assert queue.list_jobs(status=FAILED)[0].attempts == 2
    assert queue.list_pending() == []


def test_jobs_endpoint_lists_for_studio() -> None:
    queue = InMemoryJobQueue()
    cal = InMemoryCalendarRepository()
    cal.upsert(CalendarUpsert(company_ticker="INTC", next_filing_estimate=date(2026, 5, 1)))
    enqueue_due(cal, queue, theme_id="t1", tickers=["INTC"], today=NOW)

    app.dependency_overrides[get_job_queue] = lambda: queue
    try:
        client = TestClient(app)
        body = client.get("/jobs?theme_id=t1").json()
        assert len(body) == 1
        assert body[0]["company"] == "INTC" and body[0]["status"] == PENDING
        assert body[0]["trigger"] == "scheduled"
        # status filter
        assert client.get("/jobs?status=DONE").json() == []
    finally:
        app.dependency_overrides.clear()


_ = RUNNING  # status constant used by the scheduler (imported for completeness)
