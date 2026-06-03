"""[M3-GAP-07] S7 gap detection: a ticket per gap; re-run upgrades edge -> ticket closes."""

from __future__ import annotations

from services.engine.cve.gaps import EdgeAssessment, GapType, detect_gaps, sync_gaps
from services.engine.tickets.repository import InMemoryTicketRepository


def _assessment(
    *,
    confidence: str = "derived",
    status: str = "reconciled",
    freshness: str = "fresh",
    conservation_ok: bool = True,
) -> EdgeAssessment:
    return EdgeAssessment(
        edge_target="INTC->HPQ",
        confidence=confidence,
        status=status,
        freshness=freshness,
        conservation_ok=conservation_ok,
    )


def test_detect_each_gap_type() -> None:
    assert detect_gaps(_assessment(confidence="estimated")) == [GapType.ESTIMATED]
    assert detect_gaps(_assessment(status="conflict")) == [GapType.CONFLICT]
    assert detect_gaps(_assessment(freshness="stale")) == [GapType.STALE]
    assert detect_gaps(_assessment(conservation_ok=False)) == [GapType.UNCLOSED_CONSERVATION]
    assert detect_gaps(_assessment()) == []  # clean derived + fresh edge


def test_sync_opens_a_ticket_per_gap() -> None:
    repo = InMemoryTicketRepository()
    result = sync_gaps(
        _assessment(confidence="estimated", freshness="stale"), theme_id="t1", ticket_repo=repo
    )
    assert set(result.gaps) == {"gap:estimated", "gap:stale"}
    assert set(result.opened) == {"gap:estimated", "gap:stale"}
    open_metrics = {t.metric for t in repo.list_tickets("t1") if t.status == "OPEN"}
    assert open_metrics == {"gap:estimated", "gap:stale"}


def test_sync_is_idempotent() -> None:
    repo = InMemoryTicketRepository()
    sync_gaps(_assessment(confidence="estimated"), theme_id="t1", ticket_repo=repo)
    again = sync_gaps(_assessment(confidence="estimated"), theme_id="t1", ticket_repo=repo)
    assert again.opened == [] and again.closed == []
    assert len(repo.list_tickets("t1")) == 1


def test_upgrade_closes_the_gap_ticket() -> None:
    repo = InMemoryTicketRepository()
    sync_gaps(_assessment(confidence="estimated"), theme_id="t1", ticket_repo=repo)  # gap OPEN
    # Evidence uploaded -> CVE re-run upgrades the edge to derived (no longer estimated).
    result = sync_gaps(_assessment(confidence="derived"), theme_id="t1", ticket_repo=repo)
    assert result.closed == ["gap:estimated"]
    ticket = repo.list_tickets("t1")[0]
    assert ticket.metric == "gap:estimated" and ticket.status == "CLOSED"
    events = repo.list_events(ticket.id)
    assert events[-1].to_status == "CLOSED" and events[-1].actor == "cve"


def test_gap_reappearing_reopens_the_ticket() -> None:
    repo = InMemoryTicketRepository()
    sync_gaps(_assessment(confidence="estimated"), theme_id="t1", ticket_repo=repo)
    sync_gaps(_assessment(confidence="derived"), theme_id="t1", ticket_repo=repo)  # closed
    result = sync_gaps(_assessment(confidence="estimated"), theme_id="t1", ticket_repo=repo)
    assert result.opened == ["gap:estimated"]
    assert repo.list_tickets("t1")[0].status == "OPEN"
