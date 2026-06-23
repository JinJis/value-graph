"""Semiconductor cycle proxy panel — index · ETFs · memory makers (Yahoo).

A free PROXY for the memory/semiconductor cycle when DRAM/NAND spot prices aren't freely
available: the PHLX Semiconductor index, semiconductor ETFs, and the major memory makers'
share prices. Descriptive levels + day change, sourced to Yahoo, best-effort (drop on fail).

⚠ This is NOT a DRAM spot price — it's an equity/index proxy for the cycle. Labelled as such.
"""

from __future__ import annotations

import asyncio
import logging

from app.providers.registry import get_prices_provider
from app.symbols import Market, build_ref

logger = logging.getLogger(__name__)

SOURCE = "Yahoo Finance"
NOTE = "반도체 사이클 프록시(지수·ETF·메모리 제조사 주가) — DRAM 현물가가 아닙니다."

GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    ("지수", [("필라델피아 반도체지수(SOX)", "^SOX")]),
    ("ETF", [("iShares 반도체(SOXX)", "SOXX"), ("VanEck 반도체(SMH)", "SMH")]),
    ("메모리 제조사", [("마이크론", "MU"), ("삼성전자", "005930.KS"), ("SK하이닉스", "000660.KS")]),
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
        logger.info("semiconductor proxy %s (%s) failed: %s", label, ticker, exc)
        return None


async def semiconductor_proxy() -> dict:
    """Snapshot each proxy group concurrently; drop members that fail (never fabricate)."""
    out: list[dict] = []
    for name, members in GROUPS:
        rows = await asyncio.gather(*[_one(lbl, tk) for lbl, tk in members])
        kept = [r for r in rows if r]
        if kept:
            out.append({"name": name, "members": kept})
    asof = max((m["as_of"] for g in out for m in g["members"] if m.get("as_of")), default=None)
    return {"groups": out, "source": SOURCE, "note": NOTE, "as_of": asof}
