"""[M1-BLU-02] Blueprint endpoints via injected fakes (no DB, no real LLM)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from services.engine.blueprint.repository import InMemoryBlueprintRepository
from services.engine.blueprint.router import get_blueprint_repository, get_router
from services.engine.blueprint.tests.fixtures import FakeGenerator, sample_json
from services.engine.llm.router import LLMRouter
from services.engine.main import app
from services.engine.themes.models import ThemeCreate
from services.engine.themes.repository import InMemoryThemeRepository
from services.engine.themes.router import get_repository as get_theme_repository


@pytest.fixture
def ctx() -> Iterator[tuple[TestClient, InMemoryThemeRepository]]:
    themes = InMemoryThemeRepository()
    blueprints = InMemoryBlueprintRepository()
    llm = LLMRouter.from_env(env={}, generator=FakeGenerator(sample_json()))
    app.dependency_overrides[get_theme_repository] = lambda: themes
    app.dependency_overrides[get_blueprint_repository] = lambda: blueprints
    app.dependency_overrides[get_router] = lambda: llm
    yield TestClient(app), themes
    app.dependency_overrides.clear()


def test_generate_then_get_blueprint(ctx: tuple[TestClient, InMemoryThemeRepository]) -> None:
    client, themes = ctx
    theme = themes.create_theme(ThemeCreate(name="AI Data Centers"))

    generated = client.post(f"/themes/{theme.id}/blueprint")
    assert generated.status_code == 201, generated.text
    body = generated.json()
    assert body["blueprint"]["version"] == 1
    assert len(body["blueprint"]["companies"]) == 32
    assert body["coverage"]["meets_threshold"] is True
    assert body["coverage"]["company_count"] == 32
    assert len(body["coverage"]["focus_countries"]) == 5

    latest = client.get(f"/themes/{theme.id}/blueprint")
    assert latest.status_code == 200
    assert latest.json()["blueprint"]["version"] == 1


def test_generate_for_missing_theme_404(ctx: tuple[TestClient, InMemoryThemeRepository]) -> None:
    client, _ = ctx
    resp = client.post("/themes/00000000-0000-0000-0000-000000000000/blueprint")
    assert resp.status_code == 404


def test_get_before_generate_404(ctx: tuple[TestClient, InMemoryThemeRepository]) -> None:
    client, themes = ctx
    theme = themes.create_theme(ThemeCreate(name="X"))
    assert client.get(f"/themes/{theme.id}/blueprint").status_code == 404
