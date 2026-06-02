"""[M2-GEN-01] Ticket persistence + ON CONFLICT dedup against a live database.

Gated behind VALUEGRAPH_DB_TESTS=1 (requires migrations through 0005 applied).
"""

from __future__ import annotations

import os

import pytest

from services.engine.db.config import DbSettings
from services.engine.themes.models import ThemeCreate
from services.engine.themes.repository import PostgresThemeRepository
from services.engine.tickets.models import TicketCreate
from services.engine.tickets.repository import PostgresTicketRepository

pytestmark = pytest.mark.skipif(
    os.environ.get("VALUEGRAPH_DB_TESTS") != "1",
    reason="set VALUEGRAPH_DB_TESTS=1 (with Postgres up + migrations applied) to run",
)


def test_ticket_dedup_and_persist() -> None:
    settings = DbSettings.from_env()
    themes = PostgresThemeRepository(settings)
    tickets = PostgresTicketRepository(settings)
    theme = themes.create_theme(ThemeCreate(name="TICKET DBTEST"))

    first = tickets.create_open_ticket(
        theme.id, TicketCreate(target="A", metric="revenue", reason="r")
    )
    assert first is not None and first.status == "OPEN"

    duplicate = tickets.create_open_ticket(theme.id, TicketCreate(target="A", metric="revenue"))
    assert duplicate is None  # ON CONFLICT DO NOTHING

    other = tickets.create_open_ticket(theme.id, TicketCreate(target="A", metric="cogs"))
    assert other is not None

    assert len(tickets.list_tickets(theme.id)) == 2
    assert len(tickets.list_tickets(theme.id, "OPEN")) == 2
    got = tickets.get_ticket(first.id)
    assert got is not None and got.id == first.id


def test_set_resolution_persists_bound_and_is_queryable() -> None:
    settings = DbSettings.from_env()
    themes = PostgresThemeRepository(settings)
    tickets = PostgresTicketRepository(settings)
    theme = themes.create_theme(ThemeCreate(name="RESOLVE DBTEST"))
    ticket = tickets.create_open_ticket(theme.id, TicketCreate(target="A", metric="revenue"))
    assert ticket is not None

    updated = tickets.set_resolution(
        ticket.id, "UNRESOLVABLE", "not-disclosed", current_estimate={"upper_bound_pct": 10.0}
    )
    assert updated is not None
    assert updated.status == "UNRESOLVABLE" and updated.reason_code == "not-disclosed"
    assert updated.current_estimate is not None
    assert updated.current_estimate["upper_bound_pct"] == 10.0

    unresolvable = tickets.list_unresolvable(theme.id)
    assert [t.id for t in unresolvable] == [ticket.id]
    assert tickets.list_unresolvable(theme.id, target="A")[0].id == ticket.id
