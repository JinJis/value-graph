"""Commodity prices panel — metals · energy · agriculture via Yahoo futures proxies.

Descriptive levels + day change, sourced to Yahoo Finance, built on the existing prices provider
(no new upstream). Best-effort per member (failed tickers dropped, never faked). No forecasts.

Note: DRAM/NAND memory spot prices are NOT freely available (TrendForce/DRAMeXchange are paid);
they are intentionally absent here rather than proxied/faked.
"""

from __future__ import annotations

import asyncio
import logging

from app.providers.registry import get_prices_provider
from app.symbols import Market, build_ref

logger = logging.getLogger(__name__)

SOURCE = "Yahoo Finance"

# (group, [(label, Yahoo futures ticker)])
GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    ("귀금속", [("금", "GC=F"), ("은", "SI=F"), ("백금", "PL=F"), ("팔라듐", "PA=F")]),
    ("산업금속", [("구리", "HG=F")]),
    ("에너지", [("WTI 원유", "CL=F"), ("브렌트유", "BZ=F"), ("천연가스", "NG=F"), ("가솔린", "RB=F")]),
    ("농산물", [("옥수수", "ZC=F"), ("밀", "ZW=F"), ("대두", "ZS=F"), ("설탕", "SB=F"),
              ("커피", "KC=F"), ("면화", "CT=F")]),
]


async def _one(label: str, ticker: str) -> dict | None:
    try:
        snap = await get_prices_provider(Market.US).snapshot(build_ref(Market.US, ticker))
        if snap is None or snap.price is None:
            return None
        return {"label": label, "ticker": ticker, "price": snap.price,
                "change": snap.day_change, "change_percent": snap.day_change_percent,
                "as_of": (snap.time or "")[:10] or None}
    except Exception as exc:  # noqa: BLE001 — best-effort per member; drop on failure
        logger.info("commodity %s (%s) failed: %s", label, ticker, exc)
        return None


async def commodities_snapshot() -> dict:
    """Snapshot every commodity group concurrently; drop members that fail (never fabricate)."""
    out: list[dict] = []
    for name, members in GROUPS:
        rows = await asyncio.gather(*[_one(lbl, tk) for lbl, tk in members])
        kept = [r for r in rows if r]
        if kept:
            out.append({"name": name, "members": kept})
    asof = max((m["as_of"] for g in out for m in g["members"] if m.get("as_of")), default=None)
    return {"groups": out, "source": SOURCE, "as_of": asof}
