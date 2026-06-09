"""Page-backed flows (financials/calendar) are filled on their own step, never ticketed."""

from __future__ import annotations

from services.engine.tickets.models import TicketCreate
from services.engine.tickets.policy import (
    close_superseded_tickets,
    is_page_backed,
)
from services.engine.tickets.repository import InMemoryTicketRepository

THEME = "t1"


def test_is_page_backed_flags_financials_and_calendar_only() -> None:
    assert is_page_backed("financials:cogs")
    assert is_page_backed("calendar:next_filing")
    # Genuine CVE gaps without a dedicated page are NOT page-backed.
    assert not is_page_backed("entity-resolution")
    assert not is_page_backed("estimate:customer_cost_share")
    assert not is_page_backed("gap:estimated")


def test_close_superseded_retires_only_active_page_backed() -> None:
    repo = InMemoryTicketRepository()
    fin = repo.create_open_ticket(
        THEME, TicketCreate(target="3037", metric="financials:cogs", reason="x")
    )
    cal = repo.create_open_ticket(
        THEME, TicketCreate(target="NVDA", metric="calendar:next_filing", reason="x")
    )
    keep = repo.create_open_ticket(
        THEME, TicketCreate(target="2330->NVDA", metric="gap:estimated", reason="x")
    )
    assert fin and cal and keep

    closed = close_superseded_tickets(THEME, repo)
    assert closed == 2

    by_id = {t.id: t for t in repo.list_tickets(THEME)}
    assert by_id[fin.id].status == "CLOSED"
    assert by_id[cal.id].status == "CLOSED"
    assert by_id[keep.id].status == "OPEN"  # genuine gap ticket untouched

    # Idempotent: a second sweep closes nothing more.
    assert close_superseded_tickets(THEME, repo) == 0
