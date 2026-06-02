"""[M1-DISC-04] RESEARCH discovery: merge + entity-resolve + Source attribution."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from services.engine.blueprint.discover import discover_companies
from services.engine.blueprint.models import Blueprint, BlueprintCompany, BlueprintRecord
from services.engine.blueprint.repository import InMemoryBlueprintRepository
from services.engine.blueprint.router import get_blueprint_repository, get_router
from services.engine.blueprint.tests.fixtures import FakeGenerator, sample_theme
from services.engine.llm.router import LLMRouter
from services.engine.main import app
from services.engine.themes.models import Theme, ThemeCreate
from services.engine.themes.repository import InMemoryThemeRepository
from services.engine.themes.router import get_repository as get_theme_repository


def _router(*responses: str) -> LLMRouter:
    return LLMRouter.from_env(env={}, generator=FakeGenerator(*responses))


def _base(repo: InMemoryBlueprintRepository, theme: Theme, tickers: list[str]) -> BlueprintRecord:
    companies = [
        BlueprintCompany(ticker=t, name=f"Name {t}", country="US", role="supplier")
        for t in tickers
    ]
    return repo.save(
        Blueprint(
            theme_id=theme.id,
            version=1,
            companies=companies,
            relationship_types=["SUPPLIES"],
        )
    )


def _disc(items: list[tuple[str, str]]) -> str:
    return json.dumps(
        {
            "companies": [
                {
                    "ticker": t,
                    "name": f"Name {t}",
                    "country": "JP",
                    "role": "supplier",
                    "source_url": u,
                    "source_publisher": "Pub",
                }
                for t, u in items
            ]
        }
    )


def test_discovery_merges_and_creates_sources() -> None:
    theme = sample_theme()
    bp_repo = InMemoryBlueprintRepository()
    th_repo = InMemoryThemeRepository()
    base = _base(bp_repo, theme, ["A", "B"])

    result = discover_companies(
        theme, base, _router(_disc([("C", "http://x/c"), ("D", "http://x/d")])), bp_repo, th_repo
    )

    assert result.discovered == 2
    assert result.added == 2
    assert result.sources_created == 2
    by_ticker = {c.ticker: c for c in result.final.companies}
    assert {"A", "B", "C", "D"} <= set(by_ticker)
    assert by_ticker["C"].source_url == "http://x/c"  # each discovered carries a source
    assert len(th_repo.list_sources(theme.id)) == 2  # Source rows attributed


def test_discovery_dedupes_companies_and_sources() -> None:
    theme = sample_theme()
    bp_repo = InMemoryBlueprintRepository()
    th_repo = InMemoryThemeRepository()
    base = _base(bp_repo, theme, ["A"])

    # Re-lists A, and C twice with the same citation URL.
    result = discover_companies(
        theme,
        base,
        _router(_disc([("A", "http://x/a"), ("C", "http://x/c"), ("C", "http://x/c")])),
        bp_repo,
        th_repo,
    )

    tickers = [c.ticker for c in result.final.companies]
    assert tickers.count("C") == 1  # company de-duplicated
    assert tickers.count("A") == 1
    assert result.sources_created == 2  # citation URL de-duplicated (a, c)


def test_discovery_requires_a_source_per_company() -> None:
    theme = sample_theme()
    bp_repo = InMemoryBlueprintRepository()
    th_repo = InMemoryThemeRepository()
    base = _base(bp_repo, theme, ["A"])
    no_source = json.dumps(
        {"companies": [{"ticker": "C", "name": "C", "country": "JP", "role": "r"}]}
    )
    with pytest.raises(ValidationError):
        discover_companies(theme, base, _router(no_source), bp_repo, th_repo)


@pytest.fixture
def overrides() -> Iterator[tuple[InMemoryThemeRepository, InMemoryBlueprintRepository, list[str]]]:
    th_repo = InMemoryThemeRepository()
    bp_repo = InMemoryBlueprintRepository()
    responses: list[str] = [_disc([("C", "http://x/c")])]
    app.dependency_overrides[get_theme_repository] = lambda: th_repo
    app.dependency_overrides[get_blueprint_repository] = lambda: bp_repo
    app.dependency_overrides[get_router] = lambda: _router(*responses)
    yield th_repo, bp_repo, responses
    app.dependency_overrides.clear()


def test_discover_endpoint(
    overrides: tuple[InMemoryThemeRepository, InMemoryBlueprintRepository, list[str]],
) -> None:
    th_repo, bp_repo, _ = overrides
    theme = th_repo.create_theme(ThemeCreate(name="AI Data Centers"))
    _base(bp_repo, theme, ["A", "B"])
    resp = TestClient(app).post(f"/themes/{theme.id}/blueprint/discover")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["discovered"] == 1
    assert body["sources_created"] == 1
    assert body["final"]["version"] == 2


def test_discover_without_blueprint_409(
    overrides: tuple[InMemoryThemeRepository, InMemoryBlueprintRepository, list[str]],
) -> None:
    th_repo, _, _ = overrides
    theme = th_repo.create_theme(ThemeCreate(name="X"))
    assert TestClient(app).post(f"/themes/{theme.id}/blueprint/discover").status_code == 409


@pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"),
    reason="no GOOGLE_API_KEY; skipping live RESEARCH discovery",
)
def test_live_discovery_runs() -> None:
    theme = sample_theme()
    bp_repo = InMemoryBlueprintRepository()
    th_repo = InMemoryThemeRepository()
    base = _base(bp_repo, theme, ["NVDA", "TSM"])
    result = discover_companies(theme, base, LLMRouter.from_env(), bp_repo, th_repo)
    assert result.final.version == 2
    assert result.sources_created == len(th_repo.list_sources(theme.id))
