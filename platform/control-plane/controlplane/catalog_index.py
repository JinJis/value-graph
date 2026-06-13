"""Catalog-driven entitlement resolution.

Fetches the data plane's ``/catalog`` and indexes it so the gateway can map an
incoming ``(method, path, market)`` to the connector(s) that serve it. A request
is entitled iff the project has activated at least one of those connectors.

Only paths present in the catalog are *governed*; meta/discovery paths (e.g.
``/health``, ``/catalog``) pass through ungoverned.
"""

from __future__ import annotations

import httpx

from controlplane.config import COST_UNITS, settings

# (method, path) -> list of {connector_id, markets, cost_tier}
_INDEX: dict[tuple[str, str], list[dict]] = {}


def set_catalog(connectors: list[dict]) -> None:
    index: dict[tuple[str, str], list[dict]] = {}
    for connector in connectors:
        cid = connector["id"]
        for resource in connector.get("resources", []):
            key = (resource.get("method", "GET").upper(), resource["path"])
            index.setdefault(key, []).append(
                {"connector_id": cid, "markets": resource.get("markets", []), "cost_tier": resource.get("cost_tier", "low")}
            )
    global _INDEX
    _INDEX = index


async def load_catalog_from_datasets() -> int:
    """Best-effort fetch of the data plane catalog at startup. Returns connector count."""
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            resp = await client.get(f"{settings.datasets_url}/catalog")
            resp.raise_for_status()
            connectors = resp.json().get("connectors", [])
    except Exception:
        return 0
    set_catalog(connectors)
    return len(connectors)


def is_governed(method: str, path: str) -> bool:
    return (method.upper(), path) in _INDEX


def candidate_connectors(method: str, path: str, market: str) -> list[dict]:
    """Connectors serving (method, path) for the given market, with cost tier."""
    out = []
    for entry in _INDEX.get((method.upper(), path), []):
        if not entry["markets"] or market.upper() in [m.upper() for m in entry["markets"]]:
            out.append(entry)
    return out


def cost_units(cost_tier: str) -> int:
    return COST_UNITS.get(cost_tier, 1)
