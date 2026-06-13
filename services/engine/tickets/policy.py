"""Which gap flows are handled by a dedicated Studio page — so they must NOT become tickets.

Financials (revenue + cost buckets) live on the Financials step and the Disclosure Calendar
(next-filing dates) on the Calendar step — each with manual entry + per-company Deep Research.
Opening a ticket for them just duplicates those pages, so we both refuse to create such tickets
and retire any left over from before those flows moved to their own page. Genuine CVE gaps with
no dedicated page (entity-resolution, estimates, conflicts, staleness) still ticket as normal.
"""

from __future__ import annotations

from services.engine.tickets.repository import TicketRepository
from services.engine.tickets.state import TicketStatus, validate_transition

# Metric prefixes owned by a dedicated Studio page — never ticket these.
PAGE_BACKED_PREFIXES: tuple[str, ...] = ("financials:", "calendar:")


def is_page_backed(metric: str) -> bool:
    """True if ``metric`` belongs to a flow with its own Studio page (fill there, not a ticket)."""
    return metric.startswith(PAGE_BACKED_PREFIXES)


def close_superseded_tickets(
    theme_id: str, repo: TicketRepository, *, actor: str = "system"
) -> int:
    """Close still-active page-backed tickets (leftovers from before those flows got their own
    page). Idempotent: skips already-CLOSED tickets and records an audit event for each close."""
    closed = 0
    for ticket in repo.list_tickets(theme_id):
        if ticket.status == TicketStatus.CLOSED or not is_page_backed(ticket.metric):
            continue
        validate_transition(ticket.status, TicketStatus.CLOSED)
        repo.set_status(ticket.id, TicketStatus.CLOSED)
        repo.record_event(ticket.id, ticket.status, TicketStatus.CLOSED, actor)
        closed += 1
    return closed
