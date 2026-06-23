"""Market overview endpoints (CE-1: cross-asset / 자산군)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.deps import ApiKeyDep
from app.store.commodities import commodities_snapshot
from app.store.cross_asset import cross_asset_snapshot
from app.store.sectors import sector_heatmap
from app.store.semiconductor import semiconductor_proxy
from app.store.themes import themes_snapshot

router = APIRouter(tags=["Market"])


class CrossAssetResponse(BaseModel):
    groups: list[dict]
    source: str
    as_of: str | None = None


class SectorHeatmapResponse(BaseModel):
    sectors: list[dict]
    source: str
    as_of: str | None = None


class CommoditiesResponse(BaseModel):
    groups: list[dict]
    source: str
    as_of: str | None = None


class SemiconductorProxyResponse(BaseModel):
    groups: list[dict]
    source: str
    note: str | None = None
    as_of: str | None = None


class ThemesResponse(BaseModel):
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


@router.get(
    "/market/sectors",
    response_model=SectorHeatmapResponse,
    dependencies=[ApiKeyDep],
    summary="US sector heatmap (섹터 히트맵): 11 GICS sectors via SPDR ETFs (Yahoo, descriptive)",
    description="Per-sector day change via the 11 SPDR Select Sector ETFs, ranked, sourced to Yahoo "
                "Finance. Descriptive only — no forecasts. Sectors that fail upstream are omitted "
                "(gaps drawn, never fabricated).",
)
async def get_sectors() -> SectorHeatmapResponse:
    return SectorHeatmapResponse(**(await sector_heatmap()))


@router.get(
    "/market/commodities",
    response_model=CommoditiesResponse,
    dependencies=[ApiKeyDep],
    summary="원자재 시세 (귀금속·산업금속·에너지·농산물) — Yahoo 선물, 서술적",
    description="Curated commodity futures (metals/energy/agriculture) — latest level + day change, "
                "sourced to Yahoo Finance. Descriptive only. (DRAM/메모리 현물가는 무료 소스가 없어 미포함.)",
)
async def get_commodities() -> CommoditiesResponse:
    return CommoditiesResponse(**(await commodities_snapshot()))


@router.get(
    "/market/semiconductor",
    response_model=SemiconductorProxyResponse,
    dependencies=[ApiKeyDep],
    summary="반도체 사이클 프록시 (지수·ETF·메모리 제조사) — DRAM 현물가 아님",
    description="A free proxy for the memory/semiconductor cycle (PHLX SOX index, semiconductor ETFs, "
                "memory makers' shares) — Yahoo-sourced levels + day change. NOT a DRAM spot price.",
)
async def get_semiconductor() -> SemiconductorProxyResponse:
    return SemiconductorProxyResponse(**(await semiconductor_proxy()))


@router.get(
    "/market/themes",
    response_model=ThemesResponse,
    dependencies=[ApiKeyDep],
    summary="테마/섹터 시세 — AI·반도체·배터리·청정에너지·바이오·방산·우주·지역 등 (ETF 프록시, 서술적)",
    description="Broad thematic coverage via representative ETF proxies (tech/AI · energy/resources · "
                "health/bio · industrials/defense · consumer/REIT · regions · digital assets) — level + "
                "day change, Yahoo-sourced, grouped. Descriptive only; failed members omitted (gaps drawn).",
)
async def get_themes() -> ThemesResponse:
    return ThemesResponse(**(await themes_snapshot()))
