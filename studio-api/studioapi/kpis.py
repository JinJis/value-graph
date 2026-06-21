"""KPIs (PH-DATA-5 / PH-9): a company's reported KPIs, each cited to its filing passage.

Thin proxy to the agent engine's `/agent/kpis` — forwards the user's tenant key so the
underlying RAG search is entitled + metered like any other tool call. The web BFF
authenticates with a service token and forwards the user's email.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from studioapi.config import settings
from studioapi.deps import current_user, require_service
from studioapi.models import User

router = APIRouter(prefix="/kpis", tags=["KPIs"], dependencies=[Depends(require_service)])


class KpiIn(BaseModel):
    ticker: str
    market: str | None = None
    top_k: int | None = None


@router.post("", summary="Extract a company's reported KPIs (cited to filing passages)")
async def get_kpis(body: KpiIn, user: User = Depends(current_user)) -> dict:
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            resp = await client.post(
                f"{settings.agent_engine_url}/agent/kpis",
                json={"ticker": body.ticker, "market": body.market, "top_k": body.top_k},
                headers={"X-API-KEY": user.api_key},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"KPI extraction failed: {exc}")
    if resp.status_code != 200:
        raise HTTPException(resp.status_code, "KPI extraction failed upstream.")
    return resp.json()
