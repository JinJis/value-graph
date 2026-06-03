"""[M4-PUB-04] PostgresProductionStore against a live database.

Gated behind VALUEGRAPH_DB_TESTS=1 (requires migrations through 0009 applied).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from services.engine.db.artifacts import build_from_cve
from services.engine.db.config import DbSettings
from services.engine.db.tests.test_artifacts import _state
from services.engine.publish.assemble import assemble
from services.engine.publish.gate import gate
from services.engine.publish.publish import PostgresProductionStore, publish
from services.engine.themes.models import ThemeCreate
from services.engine.themes.repository import PostgresThemeRepository

pytestmark = pytest.mark.skipif(
    os.environ.get("VALUEGRAPH_DB_TESTS") != "1",
    reason="set VALUEGRAPH_DB_TESTS=1 (with Postgres up + migrations applied) to run",
)

PUBLISHED_AT = datetime(2026, 6, 1, tzinfo=UTC)


def test_publish_persists_and_current_reflects_latest() -> None:
    settings = DbSettings.from_env()
    theme = PostgresThemeRepository(settings).create_theme(ThemeCreate(name="PUBLISH DBTEST"))
    store = PostgresProductionStore(settings)

    build = build_from_cve(_state().model_copy(update={"theme_id": theme.id}), version=1)
    assembled = assemble(build, threshold=0.5)
    report = gate(assembled, build)
    assert report.passed

    v1 = publish(assembled, report, store, actor="admin@vg", published_at=PUBLISHED_AT)
    assert v1.snapshot_version == 1 and v1.source_build_version == 1

    v2 = publish(assembled, report, store, actor="admin@vg", published_at=PUBLISHED_AT)
    assert v2.snapshot_version == 2

    current = store.current(theme.id)
    assert current is not None and current.snapshot_version == 2
    assert current.edges[0]["supplier"] == "INTC"
    assert store.list_versions(theme.id) == [1, 2]
    # Prior immutable version still retrievable.
    assert store.get(theme.id, 1) is not None
