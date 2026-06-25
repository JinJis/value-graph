"""Evidence endpoint — the original filing, in-app, for a cited figure or passage.

A utility route (not a catalog resource → gateway-proxied, no entitlement, like `/company/search`).
`/evidence/html` serves the filing as sanitized HTML (US iXBRL primary doc · KR OpenDART
document.xml) so the web viewer renders the *real* document and highlights the cited element in the
DOM. A gap → `204`, and the UI degrades to the external "원문 보기" link; never fabricated.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Response

from app.deps import ApiKeyDep
from app.store.filing_html import get_filing_html

router = APIRouter(tags=["Evidence"])
log = logging.getLogger(__name__)

_HTML_CACHE = {"cache-control": "public, max-age=86400"}


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
