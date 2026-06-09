"""[M7-CAL-02] Disclosure-calendar endpoints — fill the per-company filing schedule.

The calendar drives each figure's ``next_expected_update`` (read by the CVE score stage). It
ships persistence + cadence estimation but had no way to POPULATE it, so the table stayed
empty and every edge was missing ``next_expected_update`` (a required SuppliesEdge field) →
demoted to a drawn gap. These read/write endpoints let the admin fill it per company so those
gaps can become verified edges on the next build.

Read-only of Production it is NOT — this writes the Postgres ``disclosure_calendar`` (Studio
admin surface), the same two-track side as tickets/financials. It never touches the published
graph; the schedule only takes effect on the next CVE re-run + publish.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.engine.blueprint.repository import BlueprintRepository
from services.engine.blueprint.router import get_blueprint_repository
from services.engine.calendar.models import CalendarUpsert
from services.engine.calendar.repository import CalendarRepository, PostgresCalendarRepository
from services.engine.calendar.schedule import cadence_label, next_filing
from services.engine.db.config import DbSettings
from services.engine.themes.repository import ThemeRepository
from services.engine.themes.router import get_repository as get_theme_repository

router = APIRouter(tags=["calendar"])


def get_calendar_repository() -> CalendarRepository:
    return PostgresCalendarRepository(DbSettings.from_env())


ThemeRepoDep = Annotated[ThemeRepository, Depends(get_theme_repository)]
BlueprintRepoDep = Annotated[BlueprintRepository, Depends(get_blueprint_repository)]
CalendarRepoDep = Annotated[CalendarRepository, Depends(get_calendar_repository)]


class CalendarRow(BaseModel):
    """One company's filing schedule, merged with its blueprint identity. ``covered`` is true
    once a ``next_filing_estimate`` exists — that's what unblocks the edge's next_expected_update.
    """

    ticker: str
    name: str
    fiscal_calendar: str | None = None
    last_filing_date: date | None = None
    cadence_days: int | None = None
    next_filing_estimate: date | None = None
    source: str | None = None
    covered: bool = False


class CalendarCoverage(BaseModel):
    theme_id: str
    covered: int  # companies with a next_filing_estimate
    total: int
    rows: list[CalendarRow]


def _row(ticker: str, name: str, repo: CalendarRepository) -> CalendarRow:
    entry = repo.get(ticker)
    if entry is None:
        return CalendarRow(ticker=ticker, name=name)
    return CalendarRow(
        ticker=ticker,
        name=name,
        fiscal_calendar=entry.fiscal_calendar,
        last_filing_date=entry.last_filing_date,
        cadence_days=entry.cadence_days,
        next_filing_estimate=entry.next_filing_estimate,
        source=entry.source,
        covered=entry.next_filing_estimate is not None,
    )


@router.get("/themes/{theme_id}/calendar", response_model=CalendarCoverage)
def get_calendar(
    theme_id: str, themes: ThemeRepoDep, blueprints: BlueprintRepoDep, calendar: CalendarRepoDep
) -> CalendarCoverage:
    """The disclosure calendar for a theme's blueprint companies (covered + still-missing)."""
    if themes.get_theme(theme_id) is None:
        raise HTTPException(status_code=404, detail="theme not found")
    blueprint = blueprints.get_latest(theme_id)
    companies = blueprint.companies if blueprint is not None else []
    rows = [_row(c.ticker, c.name, calendar) for c in companies]
    return CalendarCoverage(
        theme_id=theme_id,
        covered=sum(1 for r in rows if r.covered),
        total=len(rows),
        rows=rows,
    )


class CalendarEntryInput(BaseModel):
    """What the admin sets for a company. If ``next_filing_estimate`` is omitted but
    ``last_filing_date`` + ``cadence_days`` are given, the next filing is computed."""

    fiscal_calendar: str | None = None
    last_filing_date: date | None = None
    cadence_days: int | None = None
    next_filing_estimate: date | None = None
    source: str | None = None
    today: date | None = None  # anchor for the computed estimate (tests); defaults to today


@router.put("/themes/{theme_id}/calendar/{ticker}", response_model=CalendarRow)
def upsert_calendar(
    theme_id: str,
    ticker: str,
    body: CalendarEntryInput,
    themes: ThemeRepoDep,
    calendar: CalendarRepoDep,
) -> CalendarRow:
    """Set/refresh a company's filing schedule. Computes ``next_filing_estimate`` from
    last_filing_date + cadence when not given explicitly, then persists."""
    if themes.get_theme(theme_id) is None:
        raise HTTPException(status_code=404, detail="theme not found")

    estimate = body.next_filing_estimate
    cadence = body.cadence_days
    if estimate is None and body.last_filing_date is not None and cadence is not None:
        estimate = next_filing(body.last_filing_date, cadence, body.today or date.today())

    entry = calendar.upsert(
        CalendarUpsert(
            company_ticker=ticker,
            fiscal_calendar=body.fiscal_calendar or cadence_label(cadence),
            last_filing_date=body.last_filing_date,
            cadence_days=cadence,
            next_filing_estimate=estimate,
            source=body.source,
        )
    )
    return CalendarRow(
        ticker=entry.company_ticker,
        name=ticker,
        fiscal_calendar=entry.fiscal_calendar,
        last_filing_date=entry.last_filing_date,
        cadence_days=entry.cadence_days,
        next_filing_estimate=entry.next_filing_estimate,
        source=entry.source,
        covered=entry.next_filing_estimate is not None,
    )
