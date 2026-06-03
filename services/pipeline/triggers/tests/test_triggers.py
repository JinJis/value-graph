"""[M7-TRIG-03] New-filing trigger: detect, refresh calendar, enqueue a scoped CVE job."""

from __future__ import annotations

from datetime import date

from services.engine.calendar.repository import InMemoryCalendarRepository
from services.pipeline.triggers.detect import (
    affected_edge_keys,
    is_new_filing,
    on_new_filing,
)
from services.pipeline.triggers.jobs import InMemoryJobQueue
from services.pipeline.triggers.models import DONE, PENDING

TODAY = date(2026, 6, 1)
HISTORY = [date(2025, 8, 15), date(2025, 11, 15), date(2026, 2, 15)]
EDGES = [
    {"supplier": "INTC", "customer": "HPQ"},
    {"supplier": "ASML", "customer": "INTC"},
    {"supplier": "TSM", "customer": "NVDA"},
]


def test_is_new_filing() -> None:
    assert is_new_filing(None, date(2026, 5, 1)) is True
    assert is_new_filing(date(2026, 2, 15), date(2026, 5, 15)) is True
    assert is_new_filing(date(2026, 2, 15), date(2026, 2, 15)) is False  # same date
    assert is_new_filing(date(2026, 2, 15), date(2026, 1, 1)) is False  # older


def test_affected_edges_scope_to_company() -> None:
    assert affected_edge_keys(EDGES, "INTC") == ["ASML->INTC", "INTC->HPQ"]
    assert affected_edge_keys(EDGES, "NOBODY") == []


def test_on_new_filing_enqueues_scoped_job_and_updates_calendar() -> None:
    cal = InMemoryCalendarRepository()
    queue = InMemoryJobQueue()

    job = on_new_filing(
        theme_id="t1",
        company="INTC",
        filing_date=date(2026, 5, 15),
        history=HISTORY,
        calendar_repo=cal,
        job_queue=queue,
        today=TODAY,
        edges=EDGES,
    )

    assert job is not None
    assert job.trigger == "new_evidence" and job.company == "INTC"
    assert job.affected_edges == ["ASML->INTC", "INTC->HPQ"]
    assert job.status == PENDING
    assert queue.list_pending("t1") == [job]

    # Calendar absorbed the new filing and re-projected the next estimate.
    entry = cal.get("INTC")
    assert entry is not None
    assert entry.last_filing_date == date(2026, 5, 15)
    assert entry.next_filing_estimate is not None and entry.next_filing_estimate > TODAY


def test_on_new_filing_is_idempotent_for_known_filings() -> None:
    cal = InMemoryCalendarRepository()
    queue = InMemoryJobQueue()
    common = dict(
        theme_id="t1", company="INTC", history=HISTORY, calendar_repo=cal,
        job_queue=queue, today=TODAY,
    )

    first = on_new_filing(filing_date=date(2026, 5, 15), **common)  # type: ignore[arg-type]
    assert first is not None

    # Re-detecting an already-recorded filing (now the calendar's last) enqueues nothing.
    again = on_new_filing(filing_date=date(2026, 5, 15), **common)  # type: ignore[arg-type]
    assert again is None
    assert len(queue.list_pending()) == 1


def test_job_queue_lifecycle() -> None:
    queue = InMemoryJobQueue()
    cal = InMemoryCalendarRepository()
    job = on_new_filing(
        theme_id="t1", company="TSM", filing_date=date(2026, 5, 20), history=[],
        calendar_repo=cal, job_queue=queue, today=TODAY,
    )
    assert job is not None
    queue.set_status(job.id, DONE)
    assert queue.list_pending() == []  # drained
    assert queue.get(job.id).status == DONE  # type: ignore[union-attr]
