"""[M2-UNRES-04] Resolution states, the not-disclosed 10% bound, and CVE queries."""

from __future__ import annotations

from services.engine.tickets.models import TicketCreate
from services.engine.tickets.repository import InMemoryTicketRepository
from services.engine.tickets.state import (
    UNDISCLOSED_UPPER_BOUND_PCT,
    ReasonCode,
    derived_estimate,
)


def test_not_disclosed_yields_10pct_upper_bound() -> None:
    estimate = derived_estimate(ReasonCode.NOT_DISCLOSED)
    assert estimate is not None
    assert estimate["upper_bound_pct"] == UNDISCLOSED_UPPER_BOUND_PCT == 10.0


def test_other_reasons_have_no_derived_estimate() -> None:
    for reason in (ReasonCode.NOT_FOUND, ReasonCode.PAYWALLED, ReasonCode.AMBIGUOUS):
        assert derived_estimate(reason) is None


def test_set_resolution_and_list_unresolvable() -> None:
    repo = InMemoryTicketRepository()
    a = repo.create_open_ticket("theme", TicketCreate(target="A", metric="revenue"))
    b = repo.create_open_ticket("theme", TicketCreate(target="B", metric="cogs"))
    assert a is not None and b is not None

    repo.set_resolution(
        a.id, "UNRESOLVABLE", "not-disclosed", current_estimate={"upper_bound_pct": 10.0}
    )

    unresolvable = repo.list_unresolvable("theme")
    assert [t.id for t in unresolvable] == [a.id]  # b is still OPEN
    assert unresolvable[0].reason_code == "not-disclosed"
    assert unresolvable[0].current_estimate is not None
    assert unresolvable[0].current_estimate["upper_bound_pct"] == 10.0
    assert repo.list_unresolvable("theme", target="A")[0].id == a.id
    assert repo.list_unresolvable("theme", target="B") == []
