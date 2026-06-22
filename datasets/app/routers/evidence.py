"""PH-PROV3 evidence endpoint — the highlighted source filing for a cited figure.

A utility route (not a catalog resource → gateway-proxied, no entitlement, like
`/company/search`). Open the filing's cached PDF (`EvidenceDoc`), locate + highlight the
cited figure with PyMuPDF (no browser, cache-first) and stream the PNG; `/evidence/doc`
serves the real PDF for "원문 열기". Any gap → `204` so the UI degrades to the text source
card; never fabricated.
"""

from __future__ import annotations

import asyncio
import logging
import os

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse

from app.deps import ApiKeyDep
from app.store.evidence_docs import get_evidence_doc
from app.store.evidence_render import highlight_png, highlight_text_png, labels_for

router = APIRouter(tags=["Evidence"])
log = logging.getLogger(__name__)

_PNG_CACHE = {"cache-control": "public, max-age=86400"}


@router.get("/evidence", dependencies=[ApiKeyDep],
            summary="PH-PROV3: highlighted source-filing image for a cited figure",
            description="Returns image/png, or 204 when no source location is available "
                        "(the UI then falls back to the text source card).")
async def evidence(market: str, accession: str, concept: str | None = None,
                   report_period: str | None = None, value: float | None = None,
                   text: str | None = None, cik: str | None = None):
    # cached PDF + PyMuPDF highlight (no browser in the hot path). Two modes:
    #   value+concept → a statement figure;  text → a cited passage (RAG, PH-PROV3e).
    if value is not None or text:
        doc = await asyncio.to_thread(get_evidence_doc, market, accession)
        if doc and doc["status"] == "stored":
            if text:
                png = await asyncio.to_thread(highlight_text_png, doc["pdf_path"], text)
            else:
                png = await asyncio.to_thread(highlight_png, doc["pdf_path"], value, labels_for(market, concept or ""))
            if png:
                return Response(content=png, media_type="image/png", headers=_PNG_CACHE)
    log.info("evidence 204: %s %s concept=%s value=%s text=%s (no cached PDF match)",
             market, accession, concept, value, bool(text))
    return Response(status_code=204)


@router.get("/evidence/doc", dependencies=[ApiKeyDep],
            summary="PH-PROV3: the cached source-filing PDF (for '원문 열기')",
            description="Streams the real filing PDF, or 204 when none is cached.")
async def evidence_doc(market: str, accession: str):
    doc = await asyncio.to_thread(get_evidence_doc, market, accession)
    if not doc or doc["status"] != "stored" or not os.path.exists(doc["pdf_path"]):
        return Response(status_code=204)
    return FileResponse(doc["pdf_path"], media_type="application/pdf", headers=_PNG_CACHE)
