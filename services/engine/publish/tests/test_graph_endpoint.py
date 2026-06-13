"""[M5-CANVAS-01] Read-only published-graph endpoint (Terminal's render source)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from services.engine.db.artifacts import GapEdge
from services.engine.main import app
from services.engine.publish.publish import ProductionSnapshot
from services.engine.publish.router import get_production_store
from services.engine.themes.repository import InMemoryThemeRepository
from services.engine.themes.router import get_repository as get_theme_repository


def _snapshot() -> ProductionSnapshot:
    return ProductionSnapshot(
        id="snap-1",
        theme_id="theme-1",
        snapshot_version=2,
        source_build_version=1,
        published_by="admin@vg",
        published_at=datetime(2026, 6, 1, tzinfo=UTC),
        completeness=0.75,
        companies=[{"ticker": "INTC", "name": "INTC"}, {"ticker": "HPQ", "name": "HPQ"}],
        edges=[{"supplier": "INTC", "customer": "HPQ", "confidence": "derived"}],
        ghost_edges=[
            GapEdge(supplier="TSM", customer="NVDA", confidence="estimated",
                    freshness="gap", reason="missing as_of_date")
        ],
        edge_sources={
            "INTC->HPQ": [
                {"source_id": "src-intc", "url": "https://sec.gov/x", "as_of_date": "2026-05-20"}
            ]
        },
    )


class _Store:
    def current(self, theme_id: str) -> ProductionSnapshot | None:
        return _snapshot() if theme_id == "theme-1" else None

    def next_snapshot_version(self, theme_id: str) -> int:
        return 1

    def save_snapshot(self, s: ProductionSnapshot) -> ProductionSnapshot:
        return s

    def get(self, theme_id: str, v: int) -> ProductionSnapshot | None:
        return None

    def list_versions(self, theme_id: str) -> list[int]:
        return []


def test_graph_endpoint_serves_published_snapshot() -> None:
    app.dependency_overrides[get_production_store] = lambda: _Store()
    app.dependency_overrides[get_theme_repository] = lambda: InMemoryThemeRepository()
    try:
        client = TestClient(app)
        ok = client.get("/themes/theme-1/graph")
        assert ok.status_code == 200
        body = ok.json()
        assert body["snapshot_version"] == 2
        assert {c["ticker"] for c in body["companies"]} == {"INTC", "HPQ"}
        assert body["edges"][0]["supplier"] == "INTC"
        assert body["ghost_edges"][0]["customer"] == "NVDA"
        # Per-figure source links travel to the Terminal (PROV-02); an unknown source id
        # still yields a ref (has_content=False -> deep-link only).
        ref = body["edge_sources"]["INTC->HPQ"][0]
        assert ref["url"] == "https://sec.gov/x" and ref["has_content"] is False
        # No admin-only provenance leaks to the user-facing graph.
        assert "published_by" not in body

        missing = client.get("/themes/unknown/graph")
        assert missing.status_code == 404
    finally:
        app.dependency_overrides.clear()
