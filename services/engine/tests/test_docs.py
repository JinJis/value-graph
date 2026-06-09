"""Docs surface: landing page, ERD, and the enriched OpenAPI schema."""

from __future__ import annotations

from fastapi.testclient import TestClient

from services.engine.main import app

client = TestClient(app)


def test_landing_links_to_docs_and_erd() -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.text
    assert "ValueGraph Engine" in body
    # Relative links so they also work behind Studio's /engine proxy.
    assert 'href="erd"' in body and 'href="docs"' in body
    assert 'href="openapi.json"' in body


def test_erd_renders_both_stores() -> None:
    resp = client.get("/erd")
    assert resp.status_code == 200
    body = resp.text
    assert "mermaid" in body  # the diagram renderer is wired
    assert "erDiagram" in body  # Postgres relational diagram
    # Key tables + the Neo4j model are present.
    for table in ("themes_meta", "sources", "tickets", "production_snapshots", "prompt_overrides"):
        assert table in body
    assert "SUPPLIES" in body and "SOURCED_FROM" in body


def test_openapi_is_tagged_and_describes_the_service() -> None:
    spec = client.get("/openapi.json").json()
    assert spec["info"]["title"] == "ValueGraph Engine"
    assert "Two-Track" in spec["info"]["description"]
    tag_names = {t["name"] for t in spec.get("tags", [])}
    assert {"cve", "prompts", "publish", "blueprint"} <= tag_names
    # The docs pages themselves are hidden from the schema.
    assert "/erd" not in spec["paths"]


def test_swagger_ui_served() -> None:
    assert client.get("/docs").status_code == 200
