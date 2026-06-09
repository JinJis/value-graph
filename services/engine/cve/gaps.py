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


# A detailed, researchable brief per gap type — what's wrong, why it matters, and what sourced
# evidence resolves it — so the ticket is actionable instead of a bare "estimated gap".
_GAP_REASONS: dict[GapType, str] = {
    GapType.ESTIMATED: (
        "The {edge} trade share is an algorithmic estimate with no primary disclosure behind it. "
        "To upgrade it from 'estimated' to derived/verified, find a sourced figure — the "
        "supplier's disclosed revenue share from this customer, or the customer's cost-bucket "
        "share to this supplier — in a recent 10-K / annual report / earnings call / exchange "
        "filing, and attach it as a Source."
    ),
    GapType.CONFLICT: (
        "Sources disagree on the {edge} trade figure; the engine flagged the conflict rather than "
        "averaging. Find an authoritative primary disclosure that reconciles the conflicting "
        "values and note which source supersedes which."
    ),
    GapType.STALE: (
        "The {edge} figure is past its expected next filing (stale). Refresh it from the "
        "company's most recent disclosure so the relationship reflects the latest period."
    ),
    GapType.UNCLOSED_CONSERVATION: (
        "The supplier's disclosed revenue shares across its customers exceed 100% for {edge} "
        "(a conservation breach). Re-check the share figures against primary filings to find the "
        "mis-stated or double-counted disclosure."
    ),
}


def _gap_reason(gap: GapType, edge_target: str) -> str:
    return _GAP_REASONS[gap].format(edge=edge_target)


def sync_gaps(
    assessment: EdgeAssessment,
    *,
    theme_id: str,
    ticket_repo: TicketRepository,
    actor: str = "cve",
) -> GapSyncResult:
    current = {_gap_metric(gap): gap for gap in detect_gaps(assessment)}
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
            created = ticket_repo.create_open_ticket(
                theme_id,
                TicketCreate(
                    target=assessment.edge_target,
                    metric=metric,
                    reason=_gap_reason(current[metric], assessment.edge_target),
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
