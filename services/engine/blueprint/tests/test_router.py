"""[M1-BLU-02] Blueprint endpoints via injected fakes (no DB, no real LLM)."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from services.engine.blueprint.models import Blueprint, BlueprintCompany
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


def test_refine_after_generate(ctx: tuple[TestClient, InMemoryThemeRepository]) -> None:
    client, themes = ctx
    theme = themes.create_theme(ThemeCreate(name="AI Data Centers"))
    client.post(f"/themes/{theme.id}/blueprint")  # version 1

    refined = client.post(f"/themes/{theme.id}/blueprint/refine")
    assert refined.status_code == 200, refined.text
    body = refined.json()
    assert len(body["rounds"]) >= 1
    assert body["final"]["version"] >= 2
    assert body["final"]["round_meta"] is not None


def test_refine_without_blueprint_409(ctx: tuple[TestClient, InMemoryThemeRepository]) -> None:
    client, themes = ctx
    theme = themes.create_theme(ThemeCreate(name="X"))
    assert client.post(f"/themes/{theme.id}/blueprint/refine").status_code == 409


_EDIT = {
    "companies": [{"ticker": "A", "name": "Alpha", "country": "US", "role": "supplier"}],
    "relationship_types": ["SUPPLIES"],
    "notes": "hand-edited",
}


def test_put_blueprint_saves_new_version(ctx: tuple[TestClient, InMemoryThemeRepository]) -> None:
    client, themes = ctx
    theme = themes.create_theme(ThemeCreate(name="T"))

    first = client.put(f"/themes/{theme.id}/blueprint", json=_EDIT)
    assert first.status_code == 200, first.text
    assert first.json()["blueprint"]["version"] == 1
    assert first.json()["blueprint"]["generated_by"] == "admin (manual edit)"

    second = client.put(f"/themes/{theme.id}/blueprint", json=_EDIT)
    assert second.json()["blueprint"]["version"] == 2  # each edit is a new version


def test_put_blueprint_missing_theme_404(ctx: tuple[TestClient, InMemoryThemeRepository]) -> None:
    client, _ = ctx
    resp = client.put("/themes/00000000-0000-0000-0000-000000000000/blueprint", json=_EDIT)
    assert resp.status_code == 404


def test_fill_domains_backfills_and_versions() -> None:
    themes = InMemoryThemeRepository()
    blueprints = InMemoryBlueprintRepository()
    theme = themes.create_theme(ThemeCreate(name="X"))
    blueprints.save(
        Blueprint(
            theme_id=theme.id,
            version=1,
            companies=[BlueprintCompany(ticker="NVDA", name="NVIDIA", country="US", role="gpu")],
            relationship_types=["SUPPLIES"],
        )
    )
    domains_json = json.dumps({"domains": [{"ticker": "NVDA", "domain": "nvidia.com"}]})
    llm = LLMRouter.from_env(env={}, generator=FakeGenerator(domains_json))
    app.dependency_overrides[get_theme_repository] = lambda: themes
    app.dependency_overrides[get_blueprint_repository] = lambda: blueprints
    app.dependency_overrides[get_router] = lambda: llm
    try:
        resp = TestClient(app).post(f"/themes/{theme.id}/blueprint/fill-domains")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["filled"] == 1 and body["total"] == 1
        assert body["blueprint"]["version"] == 2  # saved as a new version
        assert body["blueprint"]["companies"][0]["domain"] == "nvidia.com"
    finally:
        app.dependency_overrides.clear()


def test_fill_domains_without_blueprint_409(
    ctx: tuple[TestClient, InMemoryThemeRepository],
) -> None:
    client, themes = ctx
    theme = themes.create_theme(ThemeCreate(name="X"))
    assert client.post(f"/themes/{theme.id}/blueprint/fill-domains").status_code == 409


def test_fill_domains_missing_theme_404(
    ctx: tuple[TestClient, InMemoryThemeRepository],
) -> None:
    client, _ = ctx
    resp = client.post(
        "/themes/00000000-0000-0000-0000-000000000000/blueprint/fill-domains"
    )
    assert resp.status_code == 404


def test_approve_sets_status(ctx: tuple[TestClient, InMemoryThemeRepository]) -> None:
    client, themes = ctx
    theme = themes.create_theme(ThemeCreate(name="T"))

    # Nothing to approve until a blueprint exists.
    assert client.post(f"/themes/{theme.id}/blueprint/approve").status_code == 409

    client.put(f"/themes/{theme.id}/blueprint", json=_EDIT)
    approved = client.post(f"/themes/{theme.id}/blueprint/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"


def test_approve_missing_theme_404(ctx: tuple[TestClient, InMemoryThemeRepository]) -> None:
    client, _ = ctx
    resp = client.post("/themes/00000000-0000-0000-0000-000000000000/blueprint/approve")
    assert resp.status_code == 404
