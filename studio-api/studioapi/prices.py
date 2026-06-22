"""Prices passthrough — historical OHLCV for the trader chart.

Thin proxy to the **gateway** (control-plane) `/prices`, forwarding the user's tenant key so
the fetch is entitled + metered like any other data call (never the data plane directly —
invariant #2). The chart uses this to load a generous history independently of whatever
narrow window the agent fetched, so range/scroll show real data.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from studioapi.config import settings
from studioapi.deps import current_user, require_service
from studioapi.models import User

router = APIRouter(prefix="/prices", tags=["Prices"], dependencies=[Depends(require_service)])

_ALLOWED = {"ticker", "market", "interval", "start_date", "end_date"}


@router.get("", summary="Historical OHLCV via the gateway (entitled, metered)")
async def get_prices(request: Request, user: User = Depends(current_user)) -> dict:
    params = {k: v for k, v in request.query_params.items() if k in _ALLOWED and v}
    if not params.get("ticker"):
        raise HTTPException(400, "ticker is required.")
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            resp = await client.get(f"{settings.control_plane_url}/prices", params=params,
                                    headers={"X-API-KEY": user.api_key})
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"prices fetch failed: {exc}")
    if resp.status_code != 200:
        raise HTTPException(resp.status_code, "prices fetch failed upstream.")
    return resp.json()
