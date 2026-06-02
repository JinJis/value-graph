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
