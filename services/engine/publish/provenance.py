"""Enrich per-edge Source references with the authoritative Source record.

The graph build keeps only bare Source *nodes* (id + the graph-schema fields); the full
record — url, content_type, and whether we hold the bytes (storage_key) — lives in Postgres.
The source-highlight viewer (Studio + Terminal) needs those to decide HOW to show a citation:
embed + highlight a stored document, or deep-link to the original URL. So we fill each ref
from the live Source record at read time, keeping ``edge_sources`` provider-agnostic.
"""

from __future__ import annotations

from typing import Any

from services.engine.themes.repository import ThemeRepository


def enrich_edge_sources(
    edge_sources: dict[str, list[dict[str, Any]]], theme_repo: ThemeRepository
) -> dict[str, list[dict[str, Any]]]:
    """Return ``edge_sources`` with each ref filled in from its Source record.

    Adds/overrides ``url`` · ``type`` · ``content_type`` · ``has_content`` (we hold the
    bytes) · ``as_of_date``. Unknown source ids are left as-is with ``has_content=False``.
    """
    cache: dict[str, dict[str, Any]] = {}

    def meta(source_id: str) -> dict[str, Any]:
        if source_id not in cache:
            record = theme_repo.get_source(source_id) if source_id else None
            cache[source_id] = (
                {}
                if record is None
                else {
                    "url": record.url,
                    "type": str(record.type) if record.type is not None else None,
                    "content_type": record.content_type,
                    "has_content": record.storage_key is not None,
                    "as_of_date": (
                        record.as_of_date.isoformat() if record.as_of_date else None
                    ),
                }
            )
        return cache[source_id]

    out: dict[str, list[dict[str, Any]]] = {}
    for key, refs in edge_sources.items():
        enriched: list[dict[str, Any]] = []
        for ref in refs:
            m = meta(str(ref.get("source_id") or ""))
            enriched.append(
                {
                    **ref,
                    "url": ref.get("url") or m.get("url"),
                    "type": ref.get("type") or m.get("type"),
                    "content_type": m.get("content_type"),
                    "has_content": bool(m.get("has_content", False)),
                    "as_of_date": ref.get("as_of_date") or m.get("as_of_date"),
                }
            )
        out[key] = enriched
    return out
