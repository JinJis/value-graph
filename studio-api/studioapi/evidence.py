"""Evidence-image proxy (PH-PROV2).

The browser can't call the gateway directly (no tenant key client-side), so this streams
the highlighted source-filing screenshot from the data plane through the **gateway** with
the user's server-side tenant key — entitled + metered like any other data pull. Returns
the PNG, or 204 when no evidence is available (the UI then shows the text source card)."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, Query, Response

from studioapi.config import settings
from studioapi.deps import current_user, require_service
from studioapi.models import User

router = APIRouter(tags=["Evidence"], dependencies=[Depends(require_service)])


@router.get("/evidence", summary="Highlighted source-filing screenshot for a cited figure (via the gateway)")
async def evidence(
    market: str = Query("US"),
    accession: str = Query(...),
    concept: str = Query(...),
    report_period: str = Query(...),
    value: float | None = Query(None),
    cik: str | None = Query(None),
    user: User = Depends(current_user),
):
    params: dict = {"market": market, "accession": accession, "concept": concept, "report_period": report_period}
    if value is not None:
        params["value"] = value
    if cik:
        params["cik"] = cik
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds + 40) as client:
            resp = await client.get(
                f"{settings.control_plane_url}/evidence", params=params,
                headers={"X-API-KEY": user.api_key},
            )
        if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image/"):
            return Response(content=resp.content, media_type="image/png",
                            headers={"cache-control": "private, max-age=86400"})
    except httpx.HTTPError:
        pass
    return Response(status_code=204)  # graceful fallback → UI shows the text source card


@router.get("/evidence/doc", summary="The cached source-filing PDF for '원문 열기' (via the gateway)")
async def evidence_doc(
    market: str = Query("US"),
    accession: str = Query(...),
    user: User = Depends(current_user),
):
    """Stream the real filing PDF (PH-PROV3) from the data plane through the gateway with the
    user's tenant key, so '원문 열기' opens the exact document. 204 when none is cached."""
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds + 40) as client:
            resp = await client.get(
                f"{settings.control_plane_url}/evidence/doc",
                params={"market": market, "accession": accession},
                headers={"X-API-KEY": user.api_key},
            )
        if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("application/pdf"):
            return Response(content=resp.content, media_type="application/pdf",
                            headers={"cache-control": "private, max-age=86400"})
    except httpx.HTTPError:
        pass
    return Response(status_code=204)
