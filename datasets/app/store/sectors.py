"""CE-2: US sector heatmap (섹터 히트맵).

Per-sector return via the 11 SPDR Select Sector ETFs — descriptive only (latest level + day
change), sourced to Yahoo Finance, built entirely on the EXISTING prices provider (no new
upstream). Each ETF is fetched best-effort; one that fails is DROPPED (gap drawn, never
fabricated). Sectors are ranked by day change so the agent can render a sourced heatmap. No
forecasts. (KR sector indices = Wave 2, needs KRX/KIS.)
"""

from __future__ import annotations

import asyncio
import logging

from app.providers.registry import get_prices_provider
from app.symbols import Market, build_ref

logger = logging.getLogger(__name__)

SOURCE = "Yahoo Finance"

# (sector name, SPDR Select Sector ETF proxy ticker). Standard GICS sector ETFs.
SECTORS: list[tuple[str, str]] = [
    ("기술", "XLK"),
    ("금융", "XLF"),
    ("헬스케어", "XLV"),
    ("에너지", "XLE"),
    ("산업재", "XLI"),
    ("임의소비재", "XLY"),
    ("필수소비재", "XLP"),
    ("유틸리티", "XLU"),
    ("소재", "XLB"),
    ("부동산", "XLRE"),
    ("커뮤니케이션", "XLC"),
]


async def _one(sector: str, ticker: str) -> dict | None:
    try:
        snap = await get_prices_provider(Market.US).snapshot(build_ref(Market.US, ticker))
        if snap is None or snap.price is None:
            return None
        return {"sector": sector, "ticker": ticker, "price": snap.price,
                "change": snap.day_change, "change_percent": snap.day_change_percent,
                "as_of": (snap.time or "")[:10] or None}
    except Exception as exc:  # noqa: BLE001 — best-effort per ETF; drop on failure
        logger.info("sector %s (%s) failed: %s", sector, ticker, exc)
        return None


async def sector_heatmap() -> dict:
    """Snapshot every sector ETF concurrently; drop those that fail (never fabricate).
    Rank by day change (descending) so leaders/laggards read top-to-bottom."""
    rows = await asyncio.gather(*[_one(s, tk) for s, tk in SECTORS])
    kept = [r for r in rows if r]
    kept.sort(key=lambda r: (r["change_percent"] is not None, r["change_percent"] or 0), reverse=True)
    asof = max((r["as_of"] for r in kept if r.get("as_of")), default=None)
    return {"sectors": kept, "source": SOURCE, "as_of": asof}
