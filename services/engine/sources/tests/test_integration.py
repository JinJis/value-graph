"""[M2-PROC-03] Evidence Source <-> ticket linkage against a live database.

Gated behind VALUEGRAPH_DB_TESTS=1 (requires migrations through 0006 applied).
"""

from __future__ import annotations

import os
from datetime import date

import pytest

from services.engine.db.config import DbSettings
from services.engine.themes.models import SourceCreate, ThemeCreate
from services.engine.themes.repository import PostgresThemeRepository
from services.engine.tickets.models import TicketCreate
from services.engine.tickets.repository import PostgresTicketRepository

pytestmark = pytest.mark.skipif(
    os.environ.get("VALUEGRAPH_DB_TESTS") != "1",
    reason="set VALUEGRAPH_DB_TESTS=1 (with Postgres up + migrations applied) to run",
)


def test_evidence_links_to_ticket_and_status_submitted() -> None:
    settings = DbSettings.from_env()
    themes = PostgresThemeRepository(settings)
    tickets = PostgresTicketRepository(settings)

    theme = themes.create_theme(ThemeCreate(name="EVIDENCE DBTEST"))
    ticket = tickets.create_open_ticket(theme.id, TicketCreate(target="A", metric="revenue"))
    assert ticket is not None

    source = themes.add_source(
        theme.id,
        SourceCreate(type="filing", url="https://x", as_of_date=date(2026, 3, 31)),
        ticket_id=ticket.id,
    )
    assert source.ticket_id == ticket.id
    assert source.as_of_date == date(2026, 3, 31)
    assert [s.id for s in themes.list_sources_for_ticket(ticket.id)] == [source.id]

    updated = tickets.set_status(ticket.id, "SUBMITTED")
    assert updated is not None and updated.status == "SUBMITTED"
