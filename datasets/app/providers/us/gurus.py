"""Superinvestor ("거장") registry — famous investors → their SEC 13F filer CIK.

PH-DATA-1: surface each guru's latest 13F portfolio so users can follow what the masters
hold, with **every position cited to the actual SEC 13F filing** (our provenance wedge — vs
competitors that show holdings as an opaque feed). CIKs verified against SEC EDGAR (each
entity files 13F-HR). Reuses the existing 13F provider for the holdings.
"""

from __future__ import annotations

# slug → famous-investor 13F filer. Ordered by general prominence.
GURUS: list[dict] = [
    {"slug": "buffett", "name": "Berkshire Hathaway", "investor": "Warren Buffett",
     "cik": "0001067983", "description": "가치투자의 대명사 — 버크셔 해서웨이."},
    {"slug": "burry", "name": "Scion Asset Management", "investor": "Michael Burry",
     "cik": "0001649339", "description": "'빅쇼트'의 마이클 버리 — 역발상 집중투자."},
    {"slug": "ackman", "name": "Pershing Square", "investor": "Bill Ackman",
     "cik": "0001336528", "description": "행동주의 집중투자 — 빌 애크먼."},
    {"slug": "dalio", "name": "Bridgewater Associates", "investor": "Ray Dalio",
     "cik": "0001350694", "description": "세계 최대 헤지펀드 — 레이 달리오(거시/올웨더)."},
    {"slug": "klarman", "name": "Baupost Group", "investor": "Seth Klarman",
     "cik": "0001061768", "description": "안전마진의 대가 — 세스 클라먼."},
    {"slug": "loeb", "name": "Third Point", "investor": "Dan Loeb",
     "cik": "0001040273", "description": "행동주의 — 댄 러브."},
    {"slug": "einhorn", "name": "Greenlight Capital", "investor": "David Einhorn",
     "cik": "0001079114", "description": "롱숏 가치투자 — 데이비드 아인혼."},
    {"slug": "rentec", "name": "Renaissance Technologies", "investor": "Jim Simons",
     "cik": "0001037389", "description": "퀀트의 전설 — 르네상스 테크놀로지스."},
    {"slug": "druckenmiller", "name": "Duquesne Family Office", "investor": "Stanley Druckenmiller",
     "cik": "0001536411", "description": "거시 트레이딩의 거장 — 스탠리 드러켄밀러."},
    {"slug": "tepper", "name": "Appaloosa", "investor": "David Tepper",
     "cik": "0001656456", "description": "디스트레스트/거시 — 데이비드 테퍼."},
    {"slug": "icahn", "name": "Icahn Capital", "investor": "Carl Icahn",
     "cik": "0000921669", "description": "원조 행동주의 — 칼 아이칸."},
    {"slug": "marks", "name": "Oaktree Capital", "investor": "Howard Marks",
     "cik": "0000949509", "description": "신용/사이클의 대가 — 하워드 막스."},
    {"slug": "cohen", "name": "Point72", "investor": "Steve Cohen",
     "cik": "0001603466", "description": "멀티전략 — 스티브 코언."},
    {"slug": "tigerglobal", "name": "Tiger Global", "investor": "Chase Coleman",
     "cik": "0001167483", "description": "성장/테크 — 타이거 글로벌."},
    {"slug": "coatue", "name": "Coatue Management", "investor": "Philippe Laffont",
     "cik": "0001135730", "description": "테크 성장주 — 코튜."},
]

_BY_SLUG = {g["slug"]: g for g in GURUS}


def list_gurus() -> list[dict]:
    return GURUS


def get_guru(slug: str) -> dict | None:
    return _BY_SLUG.get((slug or "").strip().lower())
