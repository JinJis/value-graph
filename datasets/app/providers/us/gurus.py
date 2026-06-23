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


# --- CE-3: quarter-over-quarter trades + cross-guru common holdings -----------

def _agg_by_cusip(holdings: list) -> dict[str, dict]:
    """Aggregate 13F rows by CUSIP (a filer may split one issuer across classes/managers)."""
    out: dict[str, dict] = {}
    for h in holdings:
        cusip = getattr(h, "cusip", None)
        if not cusip:
            continue
        slot = out.setdefault(cusip, {
            "cusip": cusip, "ticker": getattr(h, "ticker", None),
            "name_of_issuer": getattr(h, "name_of_issuer", None),
            "shares": 0, "value_usd": 0, "accession_number": getattr(h, "accession_number", None),
        })
        slot["shares"] += getattr(h, "shares", 0) or 0
        slot["value_usd"] += getattr(h, "value_usd", 0) or 0
        slot["ticker"] = slot["ticker"] or getattr(h, "ticker", None)
    return out


def compute_trades(quarters: list[dict], limit: int = 40) -> dict:
    """Diff a filer's two most recent 13F quarters into discrete moves
    (new / added / trimmed / exited). `quarters` is `by_filer_quarters` output, newest first."""
    if not quarters:
        return {"trades": [], "report_period": None, "prev_report_period": None, "comparable": False}
    latest = quarters[0]
    prior = quarters[1] if len(quarters) > 1 else None
    lat = _agg_by_cusip(latest["holdings"])
    pri = _agg_by_cusip(prior["holdings"]) if prior else {}
    rows: list[dict] = []
    for cusip in set(lat) | set(pri):
        a, b = lat.get(cusip), pri.get(cusip)
        sh, psh = (a["shares"] if a else 0), (b["shares"] if b else 0)
        val, pval = (a["value_usd"] if a else 0), (b["value_usd"] if b else 0)
        if a and not b:
            action = "new"
        elif b and not a:
            action = "exited"
        elif sh > psh:
            action = "added"
        elif sh < psh:
            action = "trimmed"
        else:
            continue  # unchanged — not a move
        ref = a or b
        rows.append({
            "cusip": cusip, "ticker": ref["ticker"], "name_of_issuer": ref["name_of_issuer"],
            "action": action, "shares": sh, "prev_shares": psh, "shares_change": sh - psh,
            "shares_change_pct": round((sh - psh) / psh * 100, 1) if psh else None,
            "value_usd": val, "prev_value_usd": pval, "value_change_usd": val - pval,
            "accession_number": (a or b)["accession_number"],
        })
    rows.sort(key=lambda r: abs(r["value_change_usd"]), reverse=True)
    return {
        "trades": rows[:limit],
        "report_period": latest.get("report_period"),
        "prev_report_period": prior.get("report_period") if prior else None,
        "filing_date": latest.get("filing_date"),
        "comparable": prior is not None,
    }


def common_holdings(per_guru: list[dict], min_holders: int = 2, limit: int = 40) -> list[dict]:
    """Securities held by the most gurus right now. `per_guru` = [{guru, holdings}]."""
    bucket: dict[str, dict] = {}
    for entry in per_guru:
        g = entry["guru"]
        for cusip, slot in _agg_by_cusip(entry["holdings"]).items():
            row = bucket.setdefault(cusip, {
                "cusip": cusip, "ticker": slot["ticker"], "name_of_issuer": slot["name_of_issuer"],
                "total_value_usd": 0, "holders": [],
            })
            row["ticker"] = row["ticker"] or slot["ticker"]
            row["total_value_usd"] += slot["value_usd"]
            row["holders"].append({
                "slug": g["slug"], "investor": g["investor"], "name": g["name"],
                "shares": slot["shares"], "value_usd": slot["value_usd"],
                "accession_number": slot["accession_number"],
            })
    rows = [r for r in bucket.values() if len(r["holders"]) >= min_holders]
    for r in rows:
        r["holder_count"] = len(r["holders"])
        r["holders"].sort(key=lambda h: h["value_usd"] or 0, reverse=True)
    rows.sort(key=lambda r: (r["holder_count"], r["total_value_usd"]), reverse=True)
    return rows[:limit]
