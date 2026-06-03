"""[M4-PERSIST-01] Neo4jGraphStore against a live database: versioned round-trip.

Gated behind VALUEGRAPH_DB_TESTS=1 (requires Neo4j up + migrations through 0002).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from services.engine.db import graph
from services.engine.db.config import DbSettings
from services.engine.db.graph_store import Neo4jGraphStore
from services.engine.db.persist import persist_cve_run
from services.engine.db.tests.test_artifacts import _state

pytestmark = pytest.mark.skipif(
    os.environ.get("VALUEGRAPH_DB_TESTS") != "1",
    reason="set VALUEGRAPH_DB_TESTS=1 (with Neo4j up) to run DB integration tests",
)

CREATED = datetime(2026, 6, 1, tzinfo=UTC)
THEME = "ZZ_PERSIST_DBTEST"


def _cleanup(driver) -> None:  # type: ignore[no-untyped-def]
    with driver.session() as session:
        session.run(
            "MATCH (n) WHERE n.theme_id = $t DETACH DELETE n", t=THEME
        ).consume()


def test_build_persists_and_reconstructs_in_neo4j() -> None:
    settings = DbSettings.from_env()
    driver = graph.connect(settings)
    try:
        graph.apply_constraints(driver)
        _cleanup(driver)
        store = Neo4jGraphStore(driver)

        state = _state().model_copy(update={"theme_id": THEME})
        build = persist_cve_run(state, store, created_at=CREATED)
        assert build.version == 1

        loaded = store.load_build(THEME, 1)
        assert loaded is not None
        assert len(loaded.edges) == 1
        assert loaded.edges[0]["supplier"] == "INTC"
        assert loaded.edges[0]["customer"] == "HPQ"
        assert loaded.edges[0]["trade_value"] == 21
        assert len(loaded.gap_edges) == 1
        assert (loaded.gap_edges[0].supplier, loaded.gap_edges[0].customer) == ("TSM", "NVDA")
        assert {c["ticker"] for c in loaded.companies} == {"INTC", "HPQ", "TSM", "NVDA"}
        assert set(loaded.sources) == {"src-intc", "src-tsm"}

        # A second build increments the version; the first stays retrievable.
        persist_cve_run(state, store, created_at=CREATED)
        assert store.list_versions(THEME) == [1, 2]
    finally:
        _cleanup(driver)
        driver.close()
