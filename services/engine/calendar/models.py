"""[M7-CAL-01] Disclosure-calendar models (per-company filing schedule)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class CalendarUpsert(BaseModel):
    company_ticker: str
    fiscal_calendar: str | None = None  # e.g. "quarterly", "annual", "FY-Dec"
    last_filing_date: date | None = None
    cadence_days: int | None = None
    next_filing_estimate: date | None = None
    source: str | None = None


class CalendarEntry(BaseModel):
    id: str
    company_ticker: str
    fiscal_calendar: str | None
    last_filing_date: date | None
    cadence_days: int | None
    next_filing_estimate: date | None
    source: str | None
    updated_at: datetime
