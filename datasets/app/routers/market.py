"""Market overview endpoints (CE-1: cross-asset / 자산군)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.deps import ApiKeyDep
from app.store.cross_asset import cross_asset_snapshot

router = APIRouter(tags=["Market"])


class CrossAssetResponse(BaseModel):
    groups: list[dict]
    source: str
    as_of: str | None = None


@router.get(
    "/market/asset-classes",
    response_model=CrossAssetResponse,
    dependencies=[ApiKeyDep],
    summary="Cross-asset snapshot (자산군): indices · rates · commodities · FX · crypto (Yahoo, descriptive)",
    description="Latest level + day change for a curated cross-asset set, sourced to Yahoo Finance. "
                "Descriptive only — no forecasts. Members that fail upstream are omitted (gaps drawn).",
)
async def get_asset_classes() -> CrossAssetResponse:
    return CrossAssetResponse(**(await cross_asset_snapshot()))
