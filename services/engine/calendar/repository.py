"""[M7-CAL-01] Disclosure-calendar persistence: Protocol + in-memory + Postgres.

One row per company (disclosure_calendar). ``upsert`` refreshes a company's schedule;
``next_update_map`` feeds the figures' ``next_expected_update`` (the seam the CVE score
stage reads); ``due_before`` lists companies whose next filing has arrived (M7 re-runs).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Protocol
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from services.engine.calendar.models import CalendarEntry, CalendarUpsert
from services.engine.calendar.schedule import cadence_label, estimate_next_filing
from services.engine.db.config import DbSettings


class CalendarRepository(Protocol):
    def upsert(self, data: CalendarUpsert) -> CalendarEntry: ...

    def get(self, company_ticker: str) -> CalendarEntry | None: ...

    def list_all(self) -> list[CalendarEntry]: ...

    def due_before(self, on: date) -> list[CalendarEntry]: ...


class InMemoryCalendarRepository:
    def __init__(self) -> None:
        self._by_ticker: dict[str, CalendarEntry] = {}

    def upsert(self, data: CalendarUpsert) -> CalendarEntry:
        existing = self._by_ticker.get(data.company_ticker)
        entry = CalendarEntry(
            id=existing.id if existing else str(uuid4()),
            updated_at=datetime.now(UTC),
            **data.model_dump(),
        )
        self._by_ticker[data.company_ticker] = entry
        return entry

    def get(self, company_ticker: str) -> CalendarEntry | None:
        return self._by_ticker.get(company_ticker)

    def list_all(self) -> list[CalendarEntry]:
        return sorted(self._by_ticker.values(), key=lambda e: e.company_ticker)

    def due_before(self, on: date) -> list[CalendarEntry]:
        return [
            e
            for e in self.list_all()
            if e.next_filing_estimate is not None and e.next_filing_estimate <= on
        ]


def upsert_from_history(
    repo: CalendarRepository,
    company_ticker: str,
    history: list[date],
    *,
    today: date,
    source: str | None = None,
) -> CalendarEntry:
    """Learn a company's cadence from its filing history and persist the schedule."""
    next_estimate, cadence = estimate_next_filing(history, today=today)
    return repo.upsert(
        CalendarUpsert(
            company_ticker=company_ticker,
            fiscal_calendar=cadence_label(cadence),
            last_filing_date=max(history) if history else None,
            cadence_days=cadence,
            next_filing_estimate=next_estimate,
            source=source,
        )
    )


def next_update_map(repo: CalendarRepository, tickers: list[str]) -> dict[str, str]:
    """Build the {ticker -> next_expected_update ISO} map the CVE score stage consumes."""
    out: dict[str, str] = {}
    for ticker in tickers:
        entry = repo.get(ticker)
        if entry and entry.next_filing_estimate:
            out[ticker] = entry.next_filing_estimate.isoformat()
    return out


def _row_to_entry(row: dict[str, Any]) -> CalendarEntry:
    return CalendarEntry(
        id=str(row["id"]),
        company_ticker=row["company_ticker"],
        fiscal_calendar=row["fiscal_calendar"],
        last_filing_date=row["last_filing_date"],
        cadence_days=row["cadence_days"],
        next_filing_estimate=row["next_filing_estimate"],
        source=row["source"],
        updated_at=row["updated_at"],
    )


_COLS = (
    "id, company_ticker, fiscal_calendar, last_filing_date, cadence_days, "
    "next_filing_estimate, source, updated_at"
)


class PostgresCalendarRepository:
    def __init__(self, settings: DbSettings) -> None:
        self._dsn = settings.database_url

    def _connect(self) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(self._dsn, row_factory=dict_row)

    def upsert(self, data: CalendarUpsert) -> CalendarEntry:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO disclosure_calendar "
                "(company_ticker, fiscal_calendar, last_filing_date, cadence_days, "
                "next_filing_estimate, source) VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (company_ticker) DO UPDATE SET "
                "fiscal_calendar = EXCLUDED.fiscal_calendar, "
                "last_filing_date = EXCLUDED.last_filing_date, "
                "cadence_days = EXCLUDED.cadence_days, "
                "next_filing_estimate = EXCLUDED.next_filing_estimate, "
                "source = EXCLUDED.source, updated_at = now() "
                f"RETURNING {_COLS}",
                (
                    data.company_ticker,
                    data.fiscal_calendar,
                    data.last_filing_date,
                    data.cadence_days,
                    data.next_filing_estimate,
                    data.source,
                ),
            )
            row = cur.fetchone()
            assert row is not None
            return _row_to_entry(row)

    def get(self, company_ticker: str) -> CalendarEntry | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM disclosure_calendar WHERE company_ticker = %s",
                (company_ticker,),
            )
            row = cur.fetchone()
            return _row_to_entry(row) if row is not None else None

    def list_all(self) -> list[CalendarEntry]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT {_COLS} FROM disclosure_calendar ORDER BY company_ticker")
            return [_row_to_entry(row) for row in cur.fetchall()]

    def due_before(self, on: date) -> list[CalendarEntry]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM disclosure_calendar "
                "WHERE next_filing_estimate IS NOT NULL AND next_filing_estimate <= %s "
                "ORDER BY next_filing_estimate",
                (on,),
            )
            return [_row_to_entry(row) for row in cur.fetchall()]
