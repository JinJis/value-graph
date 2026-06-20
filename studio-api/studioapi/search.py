"""Company search proxy (U1-04).

The web BFF only talks to studio-api, but company search lives on the data plane.
This proxies `GET /company/search` through the **gateway** with the user's
server-side tenant key, so the call is entitled + metered like any other data
pull. Used by the stock-search/favorite UI to populate watchlists.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, Query

from studioapi.config import settings
from studioapi.deps import current_user, require_service
from studioapi.models import User

router = APIRouter(tags=["Search"], dependencies=[Depends(require_service)])


@router.get("/company/search", summary="Search listed companies (name or ticker), via the gateway")
async def company_search(
    q: str = Query(..., min_length=1, description="Name or ticker query."),
    market: str = Query("US", description="US or KR."),
    limit: int = Query(10, ge=1, le=50),
    user: User = Depends(current_user),
) -> dict:
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            resp = await client.get(
                f"{settings.control_plane_url}/company/search",
                params={"q": q, "market": market, "limit": limit},
                headers={"X-API-KEY": user.api_key},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError:
        return {"results": [], "query": q, "source": None, "market": market}
