"""[M2-GEN-01] Ticket endpoints via injected fakes (no DB)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from services.engine.blueprint.models import Blueprint, BlueprintCompany
from services.engine.blueprint.repository import InMemoryBlueprintRepository
from services.engine.blueprint.router import get_blueprint_repository
from services.engine.main import app
from services.engine.themes.models import Theme, ThemeCreate
from services.engine.themes.repository import InMemoryThemeRepository
from services.engine.themes.router import get_repository as get_theme_repository
from services.engine.tickets.repository import InMemoryTicketRepository
from services.engine.tickets.router import get_ticket_repository

Ctx = tuple[TestClient, InMemoryThemeRepository, InMemoryBlueprintRepository]


@pytest.fixture
def ctx() -> Iterator[Ctx]:
    themes = InMemoryThemeRepository()
    blueprints = InMemoryBlueprintRepository()
    tickets = InMemoryTicketRepository()
    app.dependency_overrides[get_theme_repository] = lambda: themes
    app.dependency_overrides[get_blueprint_repository] = lambda: blueprints
    app.dependency_overrides[get_ticket_repository] = lambda: tickets
    yield TestClient(app), themes, blueprints
    app.dependency_overrides.clear()


def _seed(
    themes: InMemoryThemeRepository,
    blueprints: InMemoryBlueprintRepository,
    *,
    approved: bool,
    with_blueprint: bool = True,
) -> Theme:
    theme = themes.create_theme(ThemeCreate(name="AI Data Centers"))
    if with_blueprint:
        blueprints.save(
            Blueprint(
                theme_id=theme.id,
                version=1,
                companies=[
                    BlueprintCompany(
                        ticker="A",
                        name="Alpha",
                        country="US",
                        role="supplier",
                        required_data_points=["revenue", "cogs"],
                    )
                ],
            )
        )
    if approved:
        themes.set_status(theme.id, "approved")
    return theme


def test_generate_and_list(ctx: Ctx) -> None:
    client, themes, blueprints = ctx
    theme = _seed(themes, blueprints, approved=True)

    generated = client.post(f"/themes/{theme.id}/tickets/generate")
    assert generated.status_code == 200, generated.text
    assert generated.json() == {"created": 2, "skipped": 0}

    again = client.post(f"/themes/{theme.id}/tickets/generate")
    assert again.json() == {"created": 0, "skipped": 2}  # idempotent

    listed = client.get(f"/themes/{theme.id}/tickets")
    assert listed.status_code == 200 and len(listed.json()) == 2
    assert len(client.get(f"/themes/{theme.id}/tickets?status=OPEN").json()) == 2
    assert len(client.get(f"/themes/{theme.id}/tickets?status=CLOSED").json()) == 0


def test_generate_requires_approved(ctx: Ctx) -> None:
    client, themes, blueprints = ctx
    theme = _seed(themes, blueprints, approved=False)
    assert client.post(f"/themes/{theme.id}/tickets/generate").status_code == 409


def test_generate_requires_blueprint(ctx: Ctx) -> None:
    client, themes, blueprints = ctx
    theme = _seed(themes, blueprints, approved=True, with_blueprint=False)
    assert client.post(f"/themes/{theme.id}/tickets/generate").status_code == 409


def test_generate_missing_theme_404(ctx: Ctx) -> None:
    client, _, _ = ctx
    resp = client.post("/themes/00000000-0000-0000-0000-000000000000/tickets/generate")
    assert resp.status_code == 404


def test_resolve_records_bound_and_carries_forward(ctx: Ctx) -> None:
    client, themes, blueprints = ctx
    theme = _seed(themes, blueprints, approved=True)
    client.post(f"/themes/{theme.id}/tickets/generate")  # 2 OPEN tickets
    ticket_id = client.get(f"/themes/{theme.id}/tickets").json()[0]["id"]

    resolved = client.post(
        f"/tickets/{ticket_id}/resolve",
        json={"status": "UNRESOLVABLE", "reason_code": "not-disclosed"},
    )
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["status"] == "UNRESOLVABLE"
    assert body["reason_code"] == "not-disclosed"
    assert body["current_estimate"]["upper_bound_pct"] == 10.0  # 10% rule recorded

    # Re-generating must NOT reset the resolved ticket back to OPEN.
    client.post(f"/themes/{theme.id}/tickets/generate")
    after = {t["id"]: t for t in client.get(f"/themes/{theme.id}/tickets").json()}
    assert after[ticket_id]["status"] == "UNRESOLVABLE"  # carries into future builds

    # CVE can query unresolvable tickets.
    unresolvable = client.get(f"/themes/{theme.id}/tickets?status=UNRESOLVABLE").json()
    assert len(unresolvable) == 1


def test_resolve_missing_ticket_404(ctx: Ctx) -> None:
    client, _, _ = ctx
    resp = client.post(
        "/tickets/00000000-0000-0000-0000-000000000000/resolve",
        json={"status": "UNRESOLVABLE", "reason_code": "not-found"},
    )
    assert resp.status_code == 404


def test_resolve_rejects_invalid_inputs(ctx: Ctx) -> None:
    client, themes, blueprints = ctx
    theme = _seed(themes, blueprints, approved=True)
    client.post(f"/themes/{theme.id}/tickets/generate")
    ticket_id = client.get(f"/themes/{theme.id}/tickets").json()[0]["id"]
    bad_reason = client.post(
        f"/tickets/{ticket_id}/resolve",
        json={"status": "UNRESOLVABLE", "reason_code": "bogus"},
    )
    assert bad_reason.status_code == 422  # unknown reason code
    bad_status = client.post(
        f"/tickets/{ticket_id}/resolve",
        json={"status": "OPEN", "reason_code": "not-found"},
    )
    assert bad_status.status_code == 422  # OPEN is not a resolution status


def test_audit_log_records_lifecycle(ctx: Ctx) -> None:
    client, themes, blueprints = ctx
    theme = _seed(themes, blueprints, approved=True)
    client.post(f"/themes/{theme.id}/tickets/generate")
    ticket_id = client.get(f"/themes/{theme.id}/tickets").json()[0]["id"]

    created_events = client.get(f"/tickets/{ticket_id}/events").json()
    assert len(created_events) == 1
    assert created_events[0]["from_status"] is None
    assert created_events[0]["to_status"] == "OPEN"
    assert created_events[0]["actor"] == "system"

    client.post(
        f"/tickets/{ticket_id}/resolve",
        json={"status": "UNRESOLVABLE", "reason_code": "not-disclosed", "actor": "alice"},
    )
    events = client.get(f"/tickets/{ticket_id}/events").json()
    assert len(events) == 2
    last = events[-1]
    assert last["from_status"] == "OPEN"
    assert last["to_status"] == "UNRESOLVABLE"
    assert last["actor"] == "alice"
    assert last["reason_code"] == "not-disclosed"


def test_invalid_transition_rejected(ctx: Ctx) -> None:
    client, themes, blueprints = ctx
    theme = _seed(themes, blueprints, approved=True)
    client.post(f"/themes/{theme.id}/tickets/generate")
    ticket_id = client.get(f"/themes/{theme.id}/tickets").json()[0]["id"]

    client.post(
        f"/tickets/{ticket_id}/resolve",
        json={"status": "UNRESOLVABLE", "reason_code": "not-found"},
    )
    # UNRESOLVABLE -> DEFERRED is not allowed by the state machine.
    rejected = client.post(
        f"/tickets/{ticket_id}/resolve",
        json={"status": "DEFERRED", "reason_code": "not-found"},
    )
    assert rejected.status_code == 409


def test_events_missing_ticket_404(ctx: Ctx) -> None:
    client, _, _ = ctx
    assert client.get("/tickets/00000000-0000-0000-0000-000000000000/events").status_code == 404
