"""Financials passthrough — income statements for the revenue/financials chart.

Like the prices proxy: forwards to the **gateway** `/financials/income-statements` with the
user's tenant key (entitled + metered — never the data plane directly). The chart uses it to
load a generous period history so left-scroll + the table's 더보기 have real data.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from studioapi.config import settings
from studioapi.deps import current_user, require_service
from studioapi.models import User

router = APIRouter(prefix="/financials", tags=["Financials"], dependencies=[Depends(require_service)])

_ALLOWED = {"ticker", "market", "period", "limit"}


@router.get("", summary="Income-statement history via the gateway (entitled, metered)")
async def get_financials(request: Request, user: User = Depends(current_user)) -> dict:
    params = {k: v for k, v in request.query_params.items() if k in _ALLOWED and v}
    if not params.get("ticker"):
        raise HTTPException(400, "ticker is required.")
    params.setdefault("period", "annual")
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            resp = await client.get(f"{settings.control_plane_url}/financials/income-statements",
                                    params=params, headers={"X-API-KEY": user.api_key})
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"financials fetch failed: {exc}")
    if resp.status_code != 200:
        raise HTTPException(resp.status_code, "financials fetch failed upstream.")
    return resp.json()
