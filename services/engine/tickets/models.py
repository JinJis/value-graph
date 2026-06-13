"""Ticket models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from services.engine.tickets.state import ReasonCode


class TicketCreate(BaseModel):
    """A required-but-unsourced data point to request."""

    target: str  # company ticker (or, later, an edge id)
    metric: str
    reason: str | None = None
    current_estimate: dict[str, Any] | None = None


class Ticket(BaseModel):
    id: str
    theme_id: str
    target: str
    metric: str
    reason: str | None
    status: str
    reason_code: str | None
    current_estimate: dict[str, Any] | None
    # A Deep Research answer awaiting the admin's review (value + cited source URL),
    # or None. Set while the ticket is OPEN; cleared on accept (evidence upload) or
    # reject. See services/engine/tickets/research.py.
    research_proposal: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class GenerateResult(BaseModel):
    created: int
    skipped: int


class ResolveRequest(BaseModel):
    """Mark a ticket UNRESOLVABLE/DEFERRED with a reason code."""

    status: Literal["UNRESOLVABLE", "DEFERRED"]
    reason_code: ReasonCode
    actor: str = "admin"  # no auth yet; captured for the audit log


class TicketEvent(BaseModel):
    """One audit-log entry: a status transition (who/what/when)."""

    id: str
    ticket_id: str
    from_status: str | None
    to_status: str
    actor: str
    reason_code: str | None
    created_at: datetime
