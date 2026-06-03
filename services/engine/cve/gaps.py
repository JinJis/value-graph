"""S7: Gap detection — emit tickets for estimated / conflict / stale /
unclosed-conservation edges, and close them when a re-run resolves the gap (PRD §6.5).

sync_gaps() is idempotent: it opens a ticket per current gap, reopens a CLOSED gap
ticket if the gap reappears, and CLOSES gap tickets whose gap is gone (e.g. an
estimated edge that uploaded evidence upgrades to derived/verified).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from services.engine.tickets.models import TicketCreate
from services.engine.tickets.repository import TicketRepository
from services.engine.tickets.state import validate_transition

GAP_METRIC_PREFIX = "gap:"


class GapType(StrEnum):
    ESTIMATED = "estimated"
    CONFLICT = "conflict"
    STALE = "stale"
    UNCLOSED_CONSERVATION = "unclosed-conservation"


class EdgeAssessment(BaseModel):
    edge_target: str  # e.g. "INTC->HPQ"
    confidence: str  # verified | derived | estimated
    status: str = "reconciled"  # reconciled | conflict
    freshness: str = "fresh"  # fresh | aging | stale | gap
    conservation_ok: bool = True


class GapSyncResult(BaseModel):
    gaps: list[str]
    opened: list[str]
    closed: list[str]


def detect_gaps(assessment: EdgeAssessment) -> list[GapType]:
    gaps: list[GapType] = []
    if assessment.status == "conflict":
        gaps.append(GapType.CONFLICT)
    if assessment.confidence == "estimated":
        gaps.append(GapType.ESTIMATED)
    if assessment.freshness == "stale":
        gaps.append(GapType.STALE)
    if not assessment.conservation_ok:
        gaps.append(GapType.UNCLOSED_CONSERVATION)
    return gaps


def _gap_metric(gap: GapType) -> str:
    return f"{GAP_METRIC_PREFIX}{gap.value}"


def sync_gaps(
    assessment: EdgeAssessment,
    *,
    theme_id: str,
    ticket_repo: TicketRepository,
    actor: str = "cve",
) -> GapSyncResult:
    current = {_gap_metric(gap) for gap in detect_gaps(assessment)}
    existing = {
        t.metric: t
        for t in ticket_repo.list_tickets(theme_id)
        if t.target == assessment.edge_target and t.metric.startswith(GAP_METRIC_PREFIX)
    }

    opened: list[str] = []
    closed: list[str] = []

    for metric in sorted(current):
        ticket = existing.get(metric)
        if ticket is None:
            label = metric.removeprefix(GAP_METRIC_PREFIX)
            created = ticket_repo.create_open_ticket(
                theme_id,
                TicketCreate(
                    target=assessment.edge_target,
                    metric=metric,
                    reason=f"{label} gap detected by CVE",
                ),
            )
            if created is not None:
                ticket_repo.record_event(created.id, None, "OPEN", actor)
                opened.append(metric)
        elif ticket.status == "CLOSED":  # gap reappeared -> reopen
            validate_transition(ticket.status, "OPEN")
            ticket_repo.set_status(ticket.id, "OPEN")
            ticket_repo.record_event(ticket.id, "CLOSED", "OPEN", actor)
            opened.append(metric)

    for metric, ticket in existing.items():
        if metric not in current and ticket.status != "CLOSED":  # gap resolved -> close
            validate_transition(ticket.status, "CLOSED")
            ticket_repo.set_status(ticket.id, "CLOSED")
            ticket_repo.record_event(ticket.id, ticket.status, "CLOSED", actor)
            closed.append(metric)

    return GapSyncResult(gaps=sorted(current), opened=sorted(opened), closed=sorted(closed))
