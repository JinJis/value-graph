"""Ticket statuses, reason codes, and the constraints unresolved tickets feed to CVE.

A "not-disclosed" mark is first-class data (PRD §8.6): it records that a company
confirmed it does NOT disclose the requested figure, which — by the CVE 10% rule —
bounds the undisclosed share at < 10%. The full state machine + audit log is
[M2-SM-05]; this module covers the resolution states and their derived estimates.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class TicketStatus(StrEnum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    UNRESOLVABLE = "UNRESOLVABLE"
    DEFERRED = "DEFERRED"


class ReasonCode(StrEnum):
    NOT_FOUND = "not-found"
    NOT_DISCLOSED = "not-disclosed"
    PAYWALLED = "paywalled"
    AMBIGUOUS = "ambiguous"


# Statuses an admin may set when a ticket cannot be closed with evidence.
RESOLUTION_STATUSES = frozenset({TicketStatus.UNRESOLVABLE, TicketStatus.DEFERRED})

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
