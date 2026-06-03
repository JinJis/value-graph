"""[M7-CAL-01] PostgresCalendarRepository against a live database.

Gated behind VALUEGRAPH_DB_TESTS=1 (requires migrations through 0011 applied).
"""

from __future__ import annotations

import os
from datetime import date

import pytest

from services.engine.calendar.models import CalendarUpsert
from services.engine.calendar.repository import PostgresCalendarRepository, upsert_from_history
from services.engine.db.config import DbSettings

pytestmark = pytest.mark.skipif(
    os.environ.get("VALUEGRAPH_DB_TESTS") != "1",
    reason="set VALUEGRAPH_DB_TESTS=1 (with Postgres up + migrations applied) to run",
)

TICKER = "ZZ_CAL_DBTEST"
TODAY = date(2026, 6, 1)


def test_calendar_upserts_and_due_before() -> None:
    settings = DbSettings.from_env()
    repo = PostgresCalendarRepository(settings)

    history = [date(2025, 5, 15), date(2025, 8, 15), date(2025, 11, 15), date(2026, 2, 15)]
    entry = upsert_from_history(repo, TICKER, history, today=TODAY, source="EDGAR")
    assert entry.next_filing_estimate is not None and entry.next_filing_estimate > TODAY

    # Upsert again -> still one row.
    again = repo.upsert(
        CalendarUpsert(company_ticker=TICKER, next_filing_estimate=date(2026, 5, 1))
    )
    assert again.id == entry.id

    assert repo.get(TICKER) is not None
    due = repo.due_before(TODAY)
    assert any(e.company_ticker == TICKER for e in due)  # 2026-05-01 <= today
