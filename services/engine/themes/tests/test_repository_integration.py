"""[M1-THEME-01] PostgresThemeRepository against a live database.

Gated behind VALUEGRAPH_DB_TESTS=1 (requires the infra stack + migrations applied).
"""

from __future__ import annotations

import os

import pytest

from services.engine.db.config import DbSettings
from services.engine.themes.models import SourceCreate, ThemeCreate
from services.engine.themes.repository import PostgresThemeRepository

pytestmark = pytest.mark.skipif(
    os.environ.get("VALUEGRAPH_DB_TESTS") != "1",
    reason="set VALUEGRAPH_DB_TESTS=1 (with Postgres up + migrations applied) to run",
)


def test_theme_and_source_roundtrip() -> None:
    repo = PostgresThemeRepository(DbSettings.from_env())

    theme = repo.create_theme(ThemeCreate(name="DBTEST theme", seed_tickers=["AAA", "BBB"]))
    fetched = repo.get_theme(theme.id)
    assert fetched is not None
    assert fetched.name == "DBTEST theme"
    assert fetched.seed_tickers == ["AAA", "BBB"]
    assert any(t.id == theme.id for t in repo.list_themes())

    record = repo.add_source(
        theme.id,
        SourceCreate(type="report", storage_key="k/x.pdf", original_filename="x.pdf"),
    )
    got = repo.get_source(record.id)
    assert got is not None and got.id == record.id
    assert [s.id for s in repo.list_sources(theme.id)] == [record.id]
