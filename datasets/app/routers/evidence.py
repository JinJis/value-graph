"""PH-PROV2 evidence endpoint — the highlighted screenshot of the exact filing line a
cited figure came from.

A utility route (not a catalog resource → gateway-proxied, no entitlement, like
`/company/search`). Looks up the precomputed `FactLocation` pointer, asks the renderer
(cache-first) to highlight that element in the real document, and streams the PNG. Any
gap — no pointer, renderer down/failed — returns `204` so the UI degrades to the text
source card. Never fabricates a location.
"""

from __future__ import annotations

import asyncio

import httpx
from fastapi import APIRouter, Response

from app.config import settings
from app.deps import ApiKeyDep
from app.http import fetch_text
from app.providers.us.sec_edgar import _UA
from app.store.locations_ingest import lookup_location

router = APIRouter(tags=["Evidence"])


async def _render(loc) -> bytes | None:
    # Fetch the filing HTML here (SEC accepts our httpx User-Agent + it's cached) and hand it
    # to the renderer — SEC 403s headless Chromium, and this avoids a second network fetch.
    html = None
    try:
        html = await fetch_text("sec_edgar", loc.primary_doc_url, headers=_UA)
    except Exception:  # noqa: BLE001 — fall back to letting the renderer try goto()
        html = None
    payload = {
        "doc_url": loc.primary_doc_url, "accession": loc.accession_number,
        "element_id": loc.element_id, "selector": loc.selector, "html": html,
    }
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds + 30) as client:
            resp = await client.post(f"{settings.renderer_url}/render/sec", json=payload)
        return resp.content if resp.status_code == 200 else None
    except Exception:  # noqa: BLE001 — renderer down → graceful fallback (204)
        return None


@router.get("/evidence/meta", dependencies=[ApiKeyDep],
            summary="PH-PROV2: is there a highlightable source location for this fact?")
async def evidence_meta(market: str, accession: str, concept: str, report_period: str,
                        cik: str | None = None) -> dict:
    loc = await asyncio.to_thread(lookup_location, market, accession, concept, report_period, cik)
    if not loc:
        return {"available": False}
    return {"available": True, "primary_doc_url": loc.primary_doc_url,
            "concept": loc.concept, "report_period": str(loc.report_period)}


@router.get("/evidence", dependencies=[ApiKeyDep],
            summary="PH-PROV2: highlighted screenshot of the filing line a figure came from",
            description="Returns image/png, or 204 when no source location is available "
                        "(the UI then falls back to the text source card).")
async def evidence(market: str, accession: str, concept: str, report_period: str,
                   value: float | None = None, cik: str | None = None):
    loc = await asyncio.to_thread(lookup_location, market, accession, concept, report_period, cik)
    if not loc:
        return Response(status_code=204)
    png = await _render(loc)
    if not png:
        return Response(status_code=204)
    return Response(content=png, media_type="image/png",
                    headers={"cache-control": "public, max-age=86400"})
