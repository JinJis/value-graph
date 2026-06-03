"""Ticket statuses, the lifecycle state machine, reason codes, and the constraints
unresolved tickets feed to CVE.

A "not-disclosed" mark is first-class data (PRD §8.6): it records that a company
confirmed it does NOT disclose the requested figure, which — by the CVE 10% rule —
bounds the undisclosed share at < 10%.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class TicketStatus(StrEnum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    UNRESOLVABLE = "UNRESOLVABLE"
    DEFERRED = "DEFERRED"
    CLOSED = "CLOSED"  # gap resolved (e.g. CVE re-run upgraded the edge)


class ReasonCode(StrEnum):
    NOT_FOUND = "not-found"
    NOT_DISCLOSED = "not-disclosed"
    PAYWALLED = "paywalled"
    AMBIGUOUS = "ambiguous"


# Statuses an admin may set when a ticket cannot be closed with evidence.
RESOLUTION_STATUSES = frozenset({TicketStatus.UNRESOLVABLE, TicketStatus.DEFERRED})


class InvalidTransition(ValueError):
    """A ticket status transition the state machine does not allow."""


# Allowed transitions. Evidence may be (re)submitted from any state — SUBMITTED is
# reachable everywhere, incl. SUBMITTED->SUBMITTED for additional evidence — while
# re-resolving (UNRESOLVABLE->DEFERRED, DEFERRED->DEFERRED) is rejected: reopen via
# new evidence first. CVE may CLOSE any active ticket when its gap is resolved, and a
# CLOSED ticket reopens (CLOSED->OPEN) if the gap reappears.
TRANSITIONS: dict[TicketStatus, frozenset[TicketStatus]] = {
    TicketStatus.OPEN: frozenset(
        {
            TicketStatus.SUBMITTED,
            TicketStatus.UNRESOLVABLE,
            TicketStatus.DEFERRED,
            TicketStatus.CLOSED,
        }
    ),
    TicketStatus.SUBMITTED: frozenset(
        {
            TicketStatus.SUBMITTED,
            TicketStatus.OPEN,
            TicketStatus.UNRESOLVABLE,
            TicketStatus.DEFERRED,
            TicketStatus.CLOSED,
        }
    ),
    TicketStatus.DEFERRED: frozenset(
        {
            TicketStatus.SUBMITTED,
            TicketStatus.OPEN,
            TicketStatus.UNRESOLVABLE,
            TicketStatus.CLOSED,
        }
    ),
    TicketStatus.UNRESOLVABLE: frozenset(
        {TicketStatus.SUBMITTED, TicketStatus.OPEN, TicketStatus.CLOSED}
    ),
    TicketStatus.CLOSED: frozenset({TicketStatus.OPEN}),
}


def can_transition(from_status: str, to_status: str) -> bool:
    try:
        src = TicketStatus(from_status)
        dst = TicketStatus(to_status)
    except ValueError:
        return False
    return dst in TRANSITIONS.get(src, frozenset())


def validate_transition(from_status: str, to_status: str) -> None:
    """Raise InvalidTransition if ``from_status -> to_status`` is not allowed."""
    if not can_transition(from_status, to_status):
        raise InvalidTransition(f"invalid ticket transition: {from_status} -> {to_status}")


# CVE 10% rule: an undisclosed customer/relationship is bounded below 10%.
UNDISCLOSED_UPPER_BOUND_PCT = 10.0


def derived_estimate(reason: ReasonCode) -> dict[str, Any] | None:
    """The constraint a reason code feeds to CVE, if any.

    "not-disclosed" (confirmed-undisclosed) caps the share at the 10% upper bound.
    """
    if reason is ReasonCode.NOT_DISCLOSED:
        return {
            "upper_bound_pct": UNDISCLOSED_UPPER_BOUND_PCT,
            "basis": "confirmed-undisclosed: 10% rule",
        }
    return None
