"""[M4-DQ-05] Data-quality meter: tier mix computed from the published graph + endpoint."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from graph_schema import is_valid
from services.engine.db.artifacts import GapEdge
from services.engine.main import app
from services.engine.publish.publish import ProductionSnapshot
from services.engine.publish.quality import compute_quality, count_quality
from services.engine.publish.router import get_production_store


def _edge(supplier: str, customer: str, confidence: str) -> dict[str, object]:
    return {"supplier": supplier, "customer": customer, "confidence": confidence}


def _snapshot(edges: list[dict[str, object]], ghosts: int) -> ProductionSnapshot:
    return ProductionSnapshot(
        id="snap-1",
        theme_id="theme-1",
        snapshot_version=3,
        source_build_version=2,
        published_by="admin@vg",
        published_at=datetime(2026, 6, 1, tzinfo=UTC),
        completeness=0.75,
        edges=edges,
        ghost_edges=[GapEdge(supplier="G", customer=str(i), confidence="estimated",
                             freshness="gap", reason="x") for i in range(ghosts)],
    )


def test_counts_by_tier_and_gap() -> None:
    edges = [
        _edge("A", "B", "verified"),
        _edge("C", "D", "derived"),
        _edge("E", "F", "derived"),
        _edge("G", "H", "estimated"),
    ]
    counts = count_quality(edges, gap_count=2)
    assert (counts.verified, counts.derived, counts.estimated, counts.gap) == (1, 2, 1, 2)
    assert counts.total == 6


def test_percentages_sum_and_validate() -> None:
    report = compute_quality(_snapshot([_edge("A", "B", "verified")], ghosts=1))
    # 1 verified + 1 gap -> 50/50.
    assert report.quality.verified == 50.0
    assert report.quality.gap == 50.0
    assert is_valid("DataQuality", report.quality.model_dump())
    assert report.total == 2 and report.snapshot_version == 3


def test_empty_graph_is_all_zero() -> None:
    report = compute_quality(_snapshot([], ghosts=0))
    q = report.quality
    assert (q.verified, q.derived, q.estimated, q.gap) == (0.0, 0.0, 0.0, 0.0)
    assert report.total == 0


def test_quality_endpoint_reads_production() -> None:
    snapshot = _snapshot([_edge("A", "B", "derived")], ghosts=1)

    class _Store:
        def current(self, theme_id: str) -> ProductionSnapshot | None:
            return snapshot if theme_id == "theme-1" else None

        def next_snapshot_version(self, theme_id: str) -> int:  # unused
            return 1

        def save_snapshot(self, s: ProductionSnapshot) -> ProductionSnapshot:
            return s

        def get(self, theme_id: str, v: int) -> ProductionSnapshot | None:
            return None

        def list_versions(self, theme_id: str) -> list[int]:
            return []

    app.dependency_overrides[get_production_store] = lambda: _Store()
    try:
        client = TestClient(app)
        ok = client.get("/themes/theme-1/quality")
        assert ok.status_code == 200
        body = ok.json()
        assert body["quality"]["derived"] == 50.0 and body["quality"]["gap"] == 50.0
        assert body["snapshot_version"] == 3

        missing = client.get("/themes/unknown/quality")
        assert missing.status_code == 404
    finally:
        app.dependency_overrides.clear()
