"""[M1-THEME-01] Theme CRUD + Additional-Context upload, via injected fakes (no DB)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.engine.main import app
from services.engine.storage.local import LocalStorage
from services.engine.themes.repository import InMemoryThemeRepository
from services.engine.themes.router import get_repository, get_storage


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    repo = InMemoryThemeRepository()
    storage = LocalStorage(tmp_path)
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_storage] = lambda: storage
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_create_list_get_theme(client: TestClient) -> None:
    created = client.post(
        "/themes", json={"name": "AI Data Centers", "seed_tickers": ["NVDA", "TSM"]}
    )
    assert created.status_code == 201, created.text
    theme = created.json()
    assert theme["name"] == "AI Data Centers"
    assert theme["seed_tickers"] == ["NVDA", "TSM"]
    assert theme["status"] == "draft"
    theme_id = theme["id"]

    listed = client.get("/themes")
    assert listed.status_code == 200
    assert any(t["id"] == theme_id for t in listed.json())

    opened = client.get(f"/themes/{theme_id}")
    assert opened.status_code == 200
    assert opened.json()["id"] == theme_id

    assert client.get("/themes/00000000-0000-0000-0000-000000000000").status_code == 404


def test_upload_source_stored_and_reopenable(client: TestClient) -> None:
    theme_id = client.post("/themes", json={"name": "T"}).json()["id"]

    files = {"file": ("broker.pdf", b"%PDF-1.7 fake content", "application/pdf")}
    uploaded = client.post(
        f"/themes/{theme_id}/sources", files=files, data={"type": "report", "publisher": "BrokerCo"}
    )
    assert uploaded.status_code == 201, uploaded.text
    source = uploaded.json()
    assert source["original_filename"] == "broker.pdf"
    assert source["type"] == "report"
    assert source["publisher"] == "BrokerCo"
    assert "storage_key" not in source  # internal key never exposed
    assert source["content_url"] == f"/sources/{source['id']}/content"

    sources = client.get(f"/themes/{theme_id}/sources")
    assert sources.status_code == 200
    assert len(sources.json()) == 1

    # Re-open the stored file (AC: files re-openable).
    content = client.get(source["content_url"])
    assert content.status_code == 200
    assert content.content == b"%PDF-1.7 fake content"
    assert content.headers["content-type"].startswith("application/pdf")


def test_upload_to_missing_theme_404(client: TestClient) -> None:
    files = {"file": ("x.txt", b"x", "text/plain")}
    resp = client.post("/themes/00000000-0000-0000-0000-000000000000/sources", files=files)
    assert resp.status_code == 404


def test_invalid_source_type_rejected(client: TestClient) -> None:
    theme_id = client.post("/themes", json={"name": "T"}).json()["id"]
    files = {"file": ("x.txt", b"x", "text/plain")}
    resp = client.post(f"/themes/{theme_id}/sources", files=files, data={"type": "forecast"})
    assert resp.status_code == 422  # "forecast" is not a valid SourceType
