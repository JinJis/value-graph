"""[M7-CAL-01] In-memory calendar repository + the next_expected_update seam."""

from __future__ import annotations

from datetime import date

from services.engine.calendar.models import CalendarUpsert
from services.engine.calendar.repository import (
    InMemoryCalendarRepository,
    next_update_map,
    upsert_from_history,
)

TODAY = date(2026, 6, 1)


def test_upsert_is_one_row_per_company() -> None:
    repo = InMemoryCalendarRepository()
    first = repo.upsert(
        CalendarUpsert(company_ticker="INTC", next_filing_estimate=date(2026, 8, 15))
    )
    second = repo.upsert(
        CalendarUpsert(company_ticker="INTC", next_filing_estimate=date(2026, 8, 20))
    )
    assert first.id == second.id  # upsert, not insert
    assert len(repo.list_all()) == 1
    latest = repo.get("INTC")
    assert latest is not None and latest.next_filing_estimate == date(2026, 8, 20)


def test_upsert_from_history_sets_estimate_and_cadence() -> None:
    repo = InMemoryCalendarRepository()
    history = [date(2025, 5, 15), date(2025, 8, 15), date(2025, 11, 15), date(2026, 2, 15)]
    entry = upsert_from_history(repo, "INTC", history, today=TODAY, source="EDGAR")

    assert entry.fiscal_calendar == "quarterly"
    assert entry.last_filing_date == date(2026, 2, 15)
    assert entry.next_filing_estimate is not None and entry.next_filing_estimate > TODAY
    assert entry.source == "EDGAR"


def test_next_update_map_powers_figures() -> None:
    repo = InMemoryCalendarRepository()
    repo.upsert(CalendarUpsert(company_ticker="INTC", next_filing_estimate=date(2026, 8, 15)))
    repo.upsert(CalendarUpsert(company_ticker="HPQ"))  # no estimate yet

    mapping = next_update_map(repo, ["INTC", "HPQ", "NVDA"])
    assert mapping == {"INTC": "2026-08-15"}  # only companies with an estimate


def test_due_before_lists_arrived_filings() -> None:
    repo = InMemoryCalendarRepository()
    repo.upsert(CalendarUpsert(company_ticker="A", next_filing_estimate=date(2026, 5, 1)))
    repo.upsert(CalendarUpsert(company_ticker="B", next_filing_estimate=date(2026, 9, 1)))

    due = repo.due_before(TODAY)
    assert [e.company_ticker for e in due] == ["A"]
