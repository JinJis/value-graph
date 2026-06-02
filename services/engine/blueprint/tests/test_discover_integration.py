"""[M1-DISC-04] Discovery persistence against a live database (fake LLM, real Postgres).

Gated behind VALUEGRAPH_DB_TESTS=1.
"""

from __future__ import annotations

import json
import os

import pytest

from services.engine.blueprint.discover import discover_companies
from services.engine.blueprint.models import Blueprint, BlueprintCompany
from services.engine.blueprint.repository import PostgresBlueprintRepository
from services.engine.blueprint.tests.fixtures import FakeGenerator
from services.engine.db.config import DbSettings
from services.engine.llm.router import LLMRouter
from services.engine.themes.models import ThemeCreate
from services.engine.themes.repository import PostgresThemeRepository

pytestmark = pytest.mark.skipif(
    os.environ.get("VALUEGRAPH_DB_TESTS") != "1",
    reason="set VALUEGRAPH_DB_TESTS=1 (with Postgres up + migrations applied) to run",
)


def _disc(items: list[tuple[str, str]]) -> str:
    return json.dumps(
        {
            "companies": [
                {"ticker": t, "name": f"Name {t}", "country": "JP", "role": "r", "source_url": u}
                for t, u in items
            ]
        }
    )


def test_discovery_persists_blueprint_version_and_sources() -> None:
    settings = DbSettings.from_env()
    themes = PostgresThemeRepository(settings)
    blueprints = PostgresBlueprintRepository(settings)

    theme = themes.create_theme(ThemeCreate(name="DISCOVER DBTEST"))
    base = blueprints.save(
        Blueprint(
            theme_id=theme.id,
            version=1,
            companies=[BlueprintCompany(ticker="A", name="A", country="US", role="r")],
            relationship_types=["SUPPLIES"],
        )
    )
    router = LLMRouter.from_env(
        env={}, generator=FakeGenerator(_disc([("C", "http://x/c"), ("D", "http://x/d")]))
    )

    result = discover_companies(theme, base, router, blueprints, themes)
    assert result.added == 2 and result.sources_created == 2
    assert result.final.version == 2

    urls = {s.url for s in themes.list_sources(theme.id)}
    assert {"http://x/c", "http://x/d"} <= urls

    latest = blueprints.get_latest(theme.id)
    assert latest is not None
    by_ticker = {c.ticker: c for c in latest.companies}
    assert by_ticker["C"].source_url == "http://x/c"  # source_url survives the jsonb roundtrip
