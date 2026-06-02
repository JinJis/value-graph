"""[M1-BLU-02] PostgresBlueprintRepository against a live database.

Gated behind VALUEGRAPH_DB_TESTS=1 (requires migrations through 0003 applied).
"""

from __future__ import annotations

import os

import pytest

from services.engine.blueprint.models import Blueprint, RoundMeta
from services.engine.blueprint.repository import PostgresBlueprintRepository
from services.engine.blueprint.tests.fixtures import sample_content
from services.engine.db.config import DbSettings
from services.engine.themes.models import ThemeCreate
from services.engine.themes.repository import PostgresThemeRepository

pytestmark = pytest.mark.skipif(
    os.environ.get("VALUEGRAPH_DB_TESTS") != "1",
    reason="set VALUEGRAPH_DB_TESTS=1 (with Postgres up + migrations applied) to run",
)


def test_blueprint_versions_persist() -> None:
    settings = DbSettings.from_env()
    themes = PostgresThemeRepository(settings)
    blueprints = PostgresBlueprintRepository(settings)

    theme = themes.create_theme(ThemeCreate(name="BLUEPRINT DBTEST"))
    content = sample_content()

    v1 = blueprints.next_version(theme.id)
    assert v1 == 1
    rec1 = blueprints.save(
        Blueprint(theme_id=theme.id, version=v1, generated_by="model-x", **content)
    )
    assert rec1.id and len(rec1.companies) == 32

    v2 = blueprints.next_version(theme.id)
    assert v2 == 2
    meta = RoundMeta(round=2, added=3, updated=1, delta=4, converged=False, generated_by="model-x")
    blueprints.save(Blueprint(theme_id=theme.id, version=v2, **content), round_meta=meta)

    latest = blueprints.get_latest(theme.id)
    assert latest is not None and latest.version == 2
    # round log (round_meta jsonb) round-trips
    assert latest.round_meta is not None
    assert latest.round_meta.delta == 4 and latest.round_meta.converged is False
