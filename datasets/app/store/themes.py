"""Thematic market panel — broad sector/theme coverage via Yahoo ETF proxies.

Investors care about many sectors & themes (AI, 반도체, 2차전지, 청정에너지, 원자력, 바이오, 방산,
우주, 로봇, 사이버보안, 핀테크, 금광, 농업, 리츠, 지역·국가, 디지털자산 …). Each theme is a
representative ETF/asset; we snapshot level + day change via the existing Yahoo provider, grouped,
best-effort (a ticker that fails upstream is dropped — gaps drawn, never faked). Descriptive only.
"""

from __future__ import annotations

import asyncio
import logging

from app.providers.registry import get_prices_provider
from app.symbols import Market, build_ref

logger = logging.getLogger(__name__)

SOURCE = "Yahoo Finance"

# (theme group, [(label, Yahoo ETF/asset proxy)]) — broad, liquid proxies; drop-on-fail at runtime.
GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    ("테크·AI", [("AI·로봇", "BOTZ"), ("AI", "AIQ"), ("반도체", "SOXX"), ("클라우드 SW", "IGV"),
               ("사이버보안", "CIBR"), ("핀테크", "FINX"), ("인터넷", "FDN")]),
    ("에너지·자원", [("청정에너지", "ICLN"), ("태양광", "TAN"), ("우라늄·원자력", "URA"),
                ("원유·가스 탐사", "XOP"), ("금광", "GDX"), ("리튬·배터리", "LIT"), ("농업", "MOO")]),
    ("헬스·바이오", [("바이오텍", "XBI"), ("헬스케어", "XLV"), ("게놈", "ARKG")]),
    ("산업·방산·인프라", [("방산", "ITA"), ("우주항공", "ARKX"), ("로봇·자동화", "ROBO"),
                  ("인프라", "PAVE"), ("항공", "JETS")]),
    ("소비·부동산", [("임의소비재", "XLY"), ("필수소비재", "XLP"), ("게임·e스포츠", "ESPO"), ("리츠", "VNQ")]),
    ("지역·국가", [("한국", "EWY"), ("중국", "MCHI"), ("일본", "EWJ"), ("인도", "INDA"),
               ("신흥국", "EEM"), ("유럽", "VGK")]),
    ("디지털자산", [("비트코인", "BTC-USD"), ("이더리움", "ETH-USD"), ("블록체인", "BLOK")]),
    # --- KR 테마 ETF (KODEX/TIGER, Yahoo .KS) — verified live ---
    ("KR 반도체·테크", [("KODEX 반도체", "091160.KS"), ("TIGER Fn반도체TOP10", "396500.KS"),
                  ("KODEX AI반도체핵심장비", "463250.KS"), ("TIGER 200 IT", "139260.KS")]),
    ("KR 2차전지·자동차", [("KODEX 2차전지산업", "305720.KS"), ("TIGER 2차전지테마", "305540.KS"),
                    ("KODEX 자동차", "091180.KS")]),
    ("KR 바이오·헬스", [("KODEX 헬스케어", "266420.KS"), ("KODEX 바이오", "244580.KS"),
                  ("TIGER 헬스케어", "385520.KS")]),
    ("KR 방산·조선·금융", [("TIGER K-방산", "449450.KS"), ("KODEX 조선TOP", "494340.KS"),
                   ("KODEX 은행", "091170.KS")]),
    ("KR 인터넷·게임·엔터", [("TIGER 인터넷TOP10", "365000.KS"), ("TIGER K-게임", "300610.KS"),
                    ("KODEX 게임산업", "300950.KS"), ("TIGER 미디어컨텐츠", "228810.KS")]),
    ("KR 고배당", [("KODEX 고배당", "279530.KS"), ("TIGER 코스피고배당", "210780.KS"),
              ("ARIRANG 고배당주", "161510.KS")]),
    ("KR 원자력", [("KINDEX 원자력테마", "433500.KS"), ("KBSTAR 글로벌원자력", "442320.KS")]),
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
        logger.info("theme %s (%s) failed: %s", label, ticker, exc)
        return None


async def themes_snapshot() -> dict:
    """Snapshot every theme group concurrently; drop members that fail (never fabricate)."""
    out: list[dict] = []
    for name, members in GROUPS:
        rows = await asyncio.gather(*[_one(lbl, tk) for lbl, tk in members])
        kept = [r for r in rows if r]
        if kept:
            out.append({"name": name, "members": kept})
    asof = max((m["as_of"] for g in out for m in g["members"] if m.get("as_of")), default=None)
    return {"groups": out, "source": SOURCE, "as_of": asof}
