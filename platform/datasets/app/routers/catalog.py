"""Catalog endpoints — discovery of available data connectors and their manifests.

Public (no API key) — this is the source of truth that drives entitlements, MCP
tool generation, RAG registration, and NL grounding on the platform.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.connectors.catalog import get_catalog, get_connector
from app.errors import not_found

router = APIRouter(tags=["Catalog"])


@router.get("/catalog", summary="List data connectors (catalog)")
async def list_catalog() -> dict:
    connectors = get_catalog()
    return {
        "count": len(connectors),
        "connectors": [c.model_dump(mode="json") for c in connectors],
    }


@router.get("/catalog/{connector_id}", summary="Get a connector manifest")
async def get_connector_manifest(connector_id: str) -> dict:
    connector = get_connector(connector_id)
    if connector is None:
        raise not_found(f"Unknown connector '{connector_id}'.")
    return connector.model_dump(mode="json")
