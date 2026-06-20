"""StubPlanner routing brain: intent keywords, ticker resolution, candidate
selection, and the deterministic stub messages.

Pure data + functions (no LLM, no I/O) extracted from ``planner.py`` so the
deterministic dev/CI router lives apart from the planner classes. ``planner.py``
re-exports the names other modules/tests reference (e.g. ``resolve_ticker``).
"""

from __future__ import annotations

import re

# task keyword -> tool-name suffix to prefer (English + Korean). Order matters:
# earlier, more specific routes win. Ticker-bearing intents come before broad search.
_ROUTES = [
    ("price", "prices"), ("주가", "prices"), ("가격", "prices"), ("시세", "prices"), ("종가", "prices"),
    ("earnings", "earnings"), ("실적", "income"), ("매출", "income"), ("영업이익", "income"),
    ("순이익", "income"), ("revenue", "income"), ("income", "income"), ("재무", "income"), ("financ", "income"),
    ("filing", "filings"), ("공시", "filings"), ("사업보고서", "filings"),
    ("insider", "insider"), ("내부자", "insider"),
    ("interest rate", "interest"), ("금리", "interest"), ("macro", "interest"), ("거시", "interest"),
    ("news", "news"), ("뉴스", "news"), ("소식", "news"),
    ("company", "company_facts"), ("profile", "company_facts"), ("개요", "company_facts"),
    ("risk", "search"), ("리스크", "search"), ("위험", "search"), ("disclos", "search"),
    ("supplier", "search"), ("공급망", "search"), ("customer", "search"),
]

# Well-known names -> ticker, so free-form questions resolve without an explicit symbol.
# 6-digit codes => KR market; alphabetic => US.
_NAME_TO_TICKER: dict[str, str] = {
    # --- KR (KRX 6-digit) ---
    "삼성전자": "005930", "samsung electronics": "005930", "sk하이닉스": "000660", "하이닉스": "000660",
    "네이버": "035420", "naver": "035420", "카카오": "035720", "kakao": "035720",
    "현대차": "005380", "현대자동차": "005380", "기아": "000270", "lg에너지솔루션": "373220",
    "포스코": "005490", "posco": "005490", "셀트리온": "068270", "삼성바이오로직스": "207940",
    "kb금융": "105560", "신한지주": "055550", "lg화학": "051910", "삼성sdi": "006400",
    # --- US ---
    "apple": "AAPL", "애플": "AAPL", "nvidia": "NVDA", "엔비디아": "NVDA", "tesla": "TSLA", "테슬라": "TSLA",
    "microsoft": "MSFT", "마이크로소프트": "MSFT", "amazon": "AMZN", "아마존": "AMZN",
    "google": "GOOGL", "alphabet": "GOOGL", "구글": "GOOGL", "meta": "META", "메타": "META",
    "intel": "INTC", "인텔": "INTC", "amd": "AMD", "tsmc": "TSM", "netflix": "NFLX", "넷플릭스": "NFLX",
}
_TICKER = re.compile(r"\b([A-Z]{1,5})\b")
_KRCODE = re.compile(r"\b(\d{6})\b")
# Finance acronyms / units that look like tickers but aren't.
_STOP = {
    "US", "KR", "I", "A", "AN", "THE", "SEC", "CEO", "CFO", "COO", "Q", "FY", "AI", "ETF", "GPU", "CPU",
    "EPS", "PER", "PBR", "PSR", "ROE", "ROA", "ROIC", "EBIT", "EBITDA", "COGS", "CAPEX", "OPEX", "FCF",
    "GDP", "CPI", "PPI", "PMI", "USD", "KRW", "JPY", "EUR", "CNY", "IPO", "NAV", "YOY", "QOQ", "TTM",
    "FED", "ECB", "BOJ", "BOE", "BOK", "IR", "PR", "ESG", "API",
}


def resolve_ticker(task: str) -> str | None:
    low = task.lower()
    # 1) known company name (longest match first so "삼성전자" beats "삼성"). ASCII
    #    names need word boundaries so "intel" doesn't fire on "intelligence".
    for name in sorted(_NAME_TO_TICKER, key=len, reverse=True):
        if name.isascii():
            if re.search(r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])", low):
                return _NAME_TO_TICKER[name]
        elif name in low:
            return _NAME_TO_TICKER[name]
    # 2) explicit KR 6-digit code
    kr = _KRCODE.search(task)
    if kr:
        return kr.group(1)
    # 3) an explicit uppercase symbol that isn't a finance acronym
    for tok in _TICKER.findall(task):
        if tok not in _STOP:
            return tok
    return None


def _market_of(ticker: str | None) -> str | None:
    if not ticker:
        return None
    return "KR" if ticker.isdigit() else "US"


def _infer_bank(task: str) -> tuple[str, str]:
    """Bank + its market for macro/interest-rate tools."""
    low = task.lower()
    if any(k in low for k in ("bok", "한국은행", "한은")) or ("한국" in task and "금리" in task):
        return "BOK", "KR"
    if "ecb" in low or "유럽" in task:
        return "ECB", "US"
    if "boj" in low or "일본" in task:
        return "BOJ", "US"
    if "boe" in low or "영국" in task:
        return "BOE", "US"
    return "FED", "US"  # default (covers fed / 연준 / 기준금리)


def _needs_ticker(tool: dict) -> bool:
    return any(p.get("name") == "ticker" for p in tool.get("params", []))


def _market_ok(tool: dict, market: str | None) -> bool:
    if market is None:
        return True
    mk = tool.get("markets")
    return not mk or market in mk


def _args_for(task: str, tool: dict, ticker: str | None, market: str | None) -> dict:
    bank, bank_market = _infer_bank(task)
    has_bank = any(p.get("name") == "bank" for p in tool.get("params", []))
    eff_market = (bank_market if has_bank else market) or "US"
    values = {
        "ticker": ticker, "market": eff_market, "period": "annual", "interval": "day",
        "start_date": "2024-01-02", "end_date": "2024-01-08", "query": task, "limit": 5, "bank": bank,
    }
    return {p["name"]: values[p["name"]] for p in tool.get("params", []) if values.get(p["name"]) is not None}


def _callable(tool: dict, args: dict, ticker: str | None) -> bool:
    """A tool is callable only if we can fill what it actually needs."""
    if _needs_ticker(tool) and not ticker:
        return False  # would 400 at the data plane without a ticker
    for p in tool.get("params", []):
        if p.get("required") and args.get(p["name"]) is None:
            return False
    return True


def _keyword_candidates(task: str, tools: dict) -> list[str]:
    """Tools whose intent the question explicitly names (keyword-driven only)."""
    low = task.lower()
    ordered: list[str] = []
    for kw, suffix in _ROUTES:
        if kw in low:
            for name in tools:
                last = name.split("__")[-1]
                if (last.startswith(suffix) or name.endswith(suffix)) and name not in ordered:
                    ordered.append(name)
    return ordered


def _ticker_fallback(tools: dict) -> list[str]:
    """When a ticker is known but no intent keyword — prefer company facts, then
    any other ticker-bearing tool."""
    ordered = [n for n in tools if n.endswith("__company_facts")]
    ordered += [n for n in tools if _needs_ticker(tools[n]) and n not in ordered]
    return ordered


def _summarize(task: str, history: list, tools: dict | None = None) -> str:
    """Deterministic stub summary — uses the connector's human-readable name (never
    the raw `{connector}__{resource}` id) and appends no canned disclaimer (the
    guardrail is a UI label; the gemini backend writes real prose)."""
    dec, res = history[-1]
    tool = (tools or {}).get(dec.tool, {})
    src = tool.get("connector_name") or tool.get("source") or res.get("connector") or "데이터 소스"
    if res["status"] == 200:
        return f"{src} 데이터를 가져왔어요. 핵심 수치와 출처는 아래 출처에서 확인하세요."
    return (
        f"{src}에서 해당 데이터를 찾지 못했어요 (상태 {res['status']}). "
        "다른 종목·기간으로 다시 시도해 보세요."
    )


def _no_tool_message(task: str, has_tools: bool) -> str:
    if not has_tools:
        return "활성화된 데이터 소스가 없습니다 — 먼저 커넥터를 활성화하세요."
    return (
        "질문에서 어떤 종목인지 파악하지 못했어요. 티커나 회사명을 넣어 주세요 — "
        "예: ‘AAPL 최근 주가’, ‘삼성전자 실적’, ‘005930 공시’, 또는 ‘Fed 기준금리’."
    )


def _user_text(conversation: list | None) -> str:
    """Concatenate the user turns of a conversation (for cross-turn context)."""
    return " ".join(
        m.get("content", "") for m in (conversation or [])
        if m.get("role") == "user" and m.get("content")
    )
