"""Evidence endpoint — the original filing, in-app, for a cited figure or passage.

A utility route (not a catalog resource → gateway-proxied, no entitlement, like `/company/search`).
`/evidence/html` serves the filing as sanitized HTML (US iXBRL primary doc · KR OpenDART
document.xml) so the web viewer renders the *real* document and highlights the cited element in the
DOM — this is the in-app viewer. The legacy `/evidence` (PyMuPDF screenshot) + `/evidence/doc`
(cached PDF) remain for now and are slated for removal once the HTML viewer fully lands. A gap →
`204`, and the UI degrades to the external "원문 보기" link; never fabricated.
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
from app.store.filing_html import get_filing_html

router = APIRouter(tags=["Evidence"])
log = logging.getLogger(__name__)

_HTML_CACHE = {"cache-control": "public, max-age=86400"}
_PNG_CACHE = {"cache-control": "public, max-age=86400"}


@router.get("/evidence/html", dependencies=[ApiKeyDep],
            summary="The original filing as sanitized HTML for the in-app viewer",
            description="US iXBRL primary doc / KR OpenDART document.xml, sanitized (scripts stripped, "
                        "strict CSP → no egress) and cached. 204 when no source markup is available "
                        "(the UI then offers the external '원문 보기' link).")
async def evidence_html(market: str, accession: str, cik: str | None = None):
    html = await get_filing_html(market, accession, cik)
    if not html:
        return Response(status_code=204)
    return Response(content=html, media_type="text/html; charset=utf-8", headers=_HTML_CACHE)


@router.get("/evidence", dependencies=[ApiKeyDep],
            summary="(legacy) highlighted source-filing image for a cited figure",
            description="Returns image/png, or 204 when no source location is available.")
async def evidence(market: str, accession: str, concept: str | None = None,
                   report_period: str | None = None, value: float | None = None,
                   text: str | None = None, cik: str | None = None):
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
            summary="(legacy) the cached source-filing PDF (for '원문 열기')",
            description="Streams the real filing PDF, or 204 when none is cached.")
async def evidence_doc(market: str, accession: str):
    doc = await asyncio.to_thread(get_evidence_doc, market, accession)
    if not doc or doc["status"] != "stored" or not os.path.exists(doc["pdf_path"]):
        return Response(status_code=204)
    return FileResponse(doc["pdf_path"], media_type="application/pdf", headers=_PNG_CACHE)
