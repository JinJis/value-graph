"""[M4-PUB-04] Publish endpoints — preview (assemble+gate, no write) and explicit publish."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from services.engine.db.artifacts import build_from_cve
from services.engine.db.graph_store import InMemoryGraphStore
from services.engine.db.tests.test_artifacts import _state
from services.engine.main import app
from services.engine.publish.publish import InMemoryProductionStore
from services.engine.publish.router import get_graph_store, get_production_store
from services.engine.themes.models import Theme, ThemeCreate
from services.engine.themes.repository import InMemoryThemeRepository
from services.engine.themes.router import get_repository as get_theme_repository


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _seed(*, drop_source: bool = False) -> tuple[Theme, InMemoryProductionStore]:
    """Seed a theme + a v1 Staging build (the _state build: 1 edge + 1 gap = 0.5 complete)."""
    themes = InMemoryThemeRepository()
    theme = themes.create_theme(ThemeCreate(name="AI Data Centers"))
    build = build_from_cve(_state(), version=1).model_copy(update={"theme_id": theme.id})
    if drop_source:
        build.sources.pop("src-intc", None)  # break the edge's Source backing
    graph = InMemoryGraphStore()
    graph.save_build(build)
    prod = InMemoryProductionStore()
    app.dependency_overrides[get_theme_repository] = lambda: themes
    app.dependency_overrides[get_graph_store] = lambda: graph
    app.dependency_overrides[get_production_store] = lambda: prod
    return theme, prod


def test_preview_threshold_gates_publish() -> None:
    theme, _ = _seed()
    client = TestClient(app)
    # Default threshold (0.7) > the build's 0.5 completeness → withheld.
    withheld = client.get(f"/themes/{theme.id}/publish/preview")
    assert withheld.status_code == 200, withheld.text
    assert withheld.json()["can_publish"] is False
    # Lower the completeness bar → publishable, gate clean.
    ok = client.get(f"/themes/{theme.id}/publish/preview?threshold=0.5")
    body = ok.json()
    assert body["can_publish"] is True
    assert body["gate"]["clean"] is True
    assert body["completeness"]["completeness"] == 0.5


def test_publish_creates_snapshot_terminal_reads() -> None:
    theme, _ = _seed()
    client = TestClient(app)
    resp = client.post(
        f"/themes/{theme.id}/publish", json={"actor": "admin@vg", "threshold": 0.5}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["snapshot_version"] == 1
    assert body["published_by"] == "admin@vg"
    assert body["overridden"] is False
    # The Terminal read-only seam now reflects the published snapshot.
    graph = client.get(f"/themes/{theme.id}/graph")
    assert graph.status_code == 200 and graph.json()["snapshot_version"] == 1


def test_publish_blocked_without_override_then_overridden() -> None:
    theme, prod = _seed(drop_source=True)
    client = TestClient(app)
    blocked = client.post(
        f"/themes/{theme.id}/publish", json={"actor": "a", "threshold": 0.5}
    )
    assert blocked.status_code == 409
    assert prod.current(theme.id) is None  # nothing leaked to Production

    overridden = client.post(
        f"/themes/{theme.id}/publish",
        json={"actor": "a", "threshold": 0.5, "override_reason": "manual review done"},
    )
    assert overridden.status_code == 200, overridden.text
    assert overridden.json()["overridden"] is True
    assert prod.current(theme.id) is not None


def test_publish_requires_a_build() -> None:
    themes = InMemoryThemeRepository()
    theme = themes.create_theme(ThemeCreate(name="X"))
    app.dependency_overrides[get_theme_repository] = lambda: themes
    app.dependency_overrides[get_graph_store] = lambda: InMemoryGraphStore()
    app.dependency_overrides[get_production_store] = lambda: InMemoryProductionStore()
    client = TestClient(app)
    assert client.get(f"/themes/{theme.id}/publish/preview").status_code == 409
    assert (
        client.post(f"/themes/{theme.id}/publish", json={"actor": "a"}).status_code == 409
    )


def test_publish_missing_theme_404() -> None:
    app.dependency_overrides[get_theme_repository] = lambda: InMemoryThemeRepository()
    app.dependency_overrides[get_graph_store] = lambda: InMemoryGraphStore()
    app.dependency_overrides[get_production_store] = lambda: InMemoryProductionStore()
    client = TestClient(app)
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.post(f"/themes/{missing}/publish", json={"actor": "a"}).status_code == 404
