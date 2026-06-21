"""PH-PROV3 evidence endpoint — the highlighted source filing for a cited figure.

A utility route (not a catalog resource → gateway-proxied, no entitlement, like
`/company/search`). Primary path (PH-PROV3): open the filing's cached PDF (`EvidenceDoc`),
locate + highlight the cited figure with PyMuPDF (no browser, cache-first) and stream the
PNG; `/evidence/doc` serves the real PDF for "원문 열기". Falls back to the legacy
`FactLocation` pointer + renderer screenshot while the concept-precompute path is retired
(PH-PROV3c). Any gap → `204` so the UI degrades to the text source card; never fabricated.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os

import httpx
from fastapi import APIRouter, Response
from fastapi.responses import FileResponse

from app.config import settings
from app.deps import ApiKeyDep
from app.http import fetch_text
from app.providers.kr.dart_document import KR_LABELS, fetch_document_markup, mark_target
from app.providers.us.sec_edgar import _UA
from app.store.evidence_docs import get_evidence_doc
from app.store.evidence_render import highlight_png, labels_for
from app.store.locations_ingest import lookup_location

router = APIRouter(tags=["Evidence"])
log = logging.getLogger(__name__)

_PNG_CACHE = {"cache-control": "public, max-age=86400"}


async def _pdf_highlight(market: str, accession: str, concept: str, value: float | None) -> bytes | None:
    """PH-PROV3: highlight the cited figure in the cached filing PDF (PyMuPDF, no browser)."""
    if value is None:
        return None
    doc = await asyncio.to_thread(get_evidence_doc, market, accession)
    if not doc or doc["status"] != "stored":
        return None
    return await asyncio.to_thread(highlight_png, doc["pdf_path"], value, labels_for(market, concept))


async def _payload_us(loc) -> dict:
    # Fetch the filing HTML here (SEC accepts our httpx User-Agent + it's cached) and hand it
    # to the renderer — SEC 403s headless Chromium, and this avoids a second network fetch.
    try:
        html = await fetch_text("sec_edgar", loc.primary_doc_url, headers=_UA)
    except Exception:  # noqa: BLE001 — fall back to letting the renderer try goto()
        html = None
    return {"doc_url": loc.primary_doc_url, "accession": loc.accession_number,
            "element_id": loc.element_id, "selector": loc.selector, "html": html}


async def _payload_kr(loc) -> dict | None:
    # DART markup is parsed by lxml at precompute but rendered by Chromium here — positional
    # XPaths diverge (implicit <tbody>, tag-case), so re-find the figure and inject a robust
    # unique #id the renderer targets. Unique per fact → no cross-fact cache-key collision.
    markup = await fetch_document_markup(loc.accession_number)
    if not markup:
        return None
    labels = KR_LABELS.get(loc.concept) or ([loc.selector] if loc.selector else [])
    eid = "vg-ev-" + hashlib.sha256(
        f"{loc.concept}|{loc.report_period}|{loc.value}".encode()).hexdigest()[:16]
    html = mark_target(markup, loc.value, labels, eid)
    if not html:
        return None
    return {"doc_url": loc.primary_doc_url, "accession": loc.accession_number,
            "element_id": eid, "selector": None, "html": html}


async def _render(loc) -> bytes | None:
    payload = await (_payload_kr(loc) if (loc.market or "").upper() == "KR" else _payload_us(loc))
    if payload is None:
        return None
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
            summary="PH-PROV3: highlighted source-filing image for a cited figure",
            description="Returns image/png, or 204 when no source location is available "
                        "(the UI then falls back to the text source card).")
async def evidence(market: str, accession: str, concept: str, report_period: str,
                   value: float | None = None, cik: str | None = None):
    # PH-PROV3: cached PDF + PyMuPDF highlight (no browser in the hot path)
    png = await _pdf_highlight(market, accession, concept, value)
    if png:
        return Response(content=png, media_type="image/png", headers=_PNG_CACHE)
    # legacy fallback: FactLocation pointer + renderer screenshot (retired in PH-PROV3d)
    loc = await asyncio.to_thread(lookup_location, market, accession, concept, report_period, cik)
    if loc:
        png = await _render(loc)
        if png:
            log.info("evidence: %s %s %s served via legacy pointer", market, accession, concept)
            return Response(content=png, media_type="image/png", headers=_PNG_CACHE)
    log.info("evidence 204: %s %s concept=%s value=%s (no cached PDF match nor pointer)",
             market, accession, concept, value)
    return Response(status_code=204)


@router.get("/evidence/doc", dependencies=[ApiKeyDep],
            summary="PH-PROV3: the cached source-filing PDF (for '원문 열기')",
            description="Streams the real filing PDF, or 204 when none is cached.")
async def evidence_doc(market: str, accession: str):
    doc = await asyncio.to_thread(get_evidence_doc, market, accession)
    if not doc or doc["status"] != "stored" or not os.path.exists(doc["pdf_path"]):
        return Response(status_code=204)
    return FileResponse(doc["pdf_path"], media_type="application/pdf", headers=_PNG_CACHE)
