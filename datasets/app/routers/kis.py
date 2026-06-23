"""CE-12: KIS — KR realtime rankings + investor flows (한국투자증권).

Live KR market data: volume rankings (활발 종목 = KR movers) and per-stock investor flows
(개인/외국인/기관 순매수 = 수급). Descriptive — no advice/forecast. Keys stay server-side.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.deps import ApiKeyDep
from app.providers.kr import kis

router = APIRouter(tags=["KR Realtime (KIS)"])


@router.get("/kr/rankings/volume", dependencies=[ApiKeyDep],
            summary="거래량 순위 (KR 활발 종목 / movers) — 한국투자증권 실시간")
async def kr_volume_rank(limit: int = Query(30, ge=1, le=100)) -> dict:
    return await kis.volume_rank(limit)


@router.get("/kr/investor-flow", dependencies=[ApiKeyDep],
            summary="투자자별 순매수 (개인·외국인·기관 수급) — 한국투자증권")
async def kr_investor_flow(
    ticker: str = Query(..., description="KR 6-digit code (e.g. 005930)."),
    limit: int = Query(10, ge=1, le=60),
) -> dict:
    return await kis.investor_flow(ticker, limit)
