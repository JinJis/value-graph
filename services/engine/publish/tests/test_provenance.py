"""Source-ref enrichment: fill each edge citation with url/content_type/has_content."""

from __future__ import annotations

from datetime import date
from typing import Any

from services.engine.publish.provenance import enrich_edge_sources
from services.engine.themes.models import SourceCreate, ThemeCreate
from services.engine.themes.repository import InMemoryThemeRepository


def test_enrich_marks_stored_vs_urlonly() -> None:
    repo = InMemoryThemeRepository()
    theme = repo.create_theme(ThemeCreate(name="T"))
    uploaded = repo.add_source(
        theme.id,
        SourceCreate(
            type="filing",
            storage_key="k1",
            content_type="application/pdf",
            as_of_date=date(2026, 5, 20),
        ),
    )
    citation = repo.add_source(
        theme.id, SourceCreate(type="report", url="https://example.com/x")
    )

    edge_sources: dict[str, list[dict[str, Any]]] = {
        "A->B": [
            {"source_id": uploaded.id, "url": None},
            {"source_id": citation.id, "url": "https://example.com/x"},
        ]
    }
    out = enrich_edge_sources(edge_sources, repo)["A->B"]

    pdf_ref = next(r for r in out if r["source_id"] == uploaded.id)
    assert pdf_ref["content_type"] == "application/pdf"
    assert pdf_ref["has_content"] is True  # we hold the bytes -> embeddable

    url_ref = next(r for r in out if r["source_id"] == citation.id)
    assert url_ref["has_content"] is False  # URL-only citation -> deep-link only
    assert url_ref["url"] == "https://example.com/x"


def test_enrich_tolerates_unknown_source() -> None:
    repo = InMemoryThemeRepository()
    out = enrich_edge_sources({"A->B": [{"source_id": "missing"}]}, repo)["A->B"]
    assert out[0]["has_content"] is False and out[0]["content_type"] is None
