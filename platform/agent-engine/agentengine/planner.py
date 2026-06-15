"""Planners: decide which tool to call (or finalize) given the task + tools.

* StubPlanner — deterministic keyword routing (dev/CI, no LLM). Calls one tool
  then summarizes. Lets the loop + provenance + guardrails be tested with no key.
* GeminiPlanner — real LLM (Gemini function calling), lazily imported.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import cache

from agentengine.config import settings

logger = logging.getLogger(__name__)


@dataclass
class Decision:
    tool: str | None = None
    args: dict | None = None
    final: str | None = None
    thought_signature: bytes | None = None


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


class StubPlanner:
    async def plan(self, task: str, tools: dict, history: list, system: str | None = None,
                   conversation: list | None = None) -> Decision:
        if history:  # already observed a tool result -> finalize
            return Decision(final=_summarize(task, history, tools))
        if not tools:
            return Decision(final=_no_tool_message(task, has_tools=False))
        # resolve the company from THIS turn, else from earlier turns (follow-ups like
        # "그럼 그 회사 주가는?" inherit the ticker named earlier in the conversation).
        ticker = resolve_ticker(task) or resolve_ticker(_user_text(conversation))
        market = _market_of(ticker)
        # keyword intent first; only fall back to ticker tools when a ticker is known
        # (a vague question with no intent/ticker gets guidance, never a doomed call).
        candidates = _keyword_candidates(task, tools)
        if not candidates and ticker:
            candidates = _ticker_fallback(tools)
        for name in candidates:
            tool = tools[name]
            if not _market_ok(tool, market):
                continue
            args = _args_for(task, tool, ticker, market)
            if _callable(tool, args, ticker):
                return Decision(tool=name, args=args)
        return Decision(final=_no_tool_message(task, has_tools=True))


def _get_text_from_response(resp) -> str | None:
    if not resp.candidates or not resp.candidates[0].content or not resp.candidates[0].content.parts:
        return None
    texts = []
    for part in resp.candidates[0].content.parts:
        if part.text:
            texts.append(part.text)
    return "".join(texts) if texts else None


class GeminiPlanner:
    """Real Gemini planner (function calling). Untested without GOOGLE_API_KEY."""

    def __init__(self, model: str) -> None:
        from google import genai

        self._genai = genai
        self._client = genai.Client()
        self.model = model

    async def plan(self, task: str, tools: dict, history: list, system: str | None = None,
                   conversation: list | None = None, force_final: bool = False) -> Decision:
        import asyncio
        from google.genai import types
        from datetime import datetime

        current_date = datetime.now().strftime("%Y-%m-%d")

        base_system = (
            "You are an expert financial-data assistant. Your goal is to answer the user's query using the provided tools.\n\n"
            f"Current Date: {current_date}\n\n"
            "Guidelines for tool selection:\n"
            "1. For stock prices, historical stock prices, EOD prices, charts, or recent market prices, use 'yahoo__prices'.\n"
            "2. For general company search, semantic queries, news, press releases, risk factors, or qualitative information, use the RAG search tool 'rag__search'.\n"
            "3. For official US public company filings, financial reports, or company profile facts, use 'sec_edgar__company_facts'.\n"
            "4. For Korean public company financial statements or reports, use 'opendart__income_statements'.\n"
            "5. For macro economy metrics like interest rates or central bank decisions, use 'fred__interest_rates' (US/global) or 'ecos__interest_rates_snapshot' (Korea).\n\n"
            "Important Parameter Instructions:\n"
            "- 'ticker': Stock tickers MUST be official symbols (e.g., 'AAPL' for Apple, '005930' for Samsung Electronics). NEVER pass company names (e.g., 'Apple', '삼성전자') as the ticker parameter.\n"
            "- Always identify the correct market ('US' or 'KR') based on the company or central bank mentioned.\n"
            "- Resolve follow-up references (e.g. 'that company') from the conversation so far.\n"
            "When you write the final answer, cite the sources you used inline as [1], [2], … in the "
            "order they first appear, so each claim is anchored to a source.\n"
            "Never predict prices or give buy/sell advice; this is not investment advice."
        )

        system_instruction = f"{base_system}\n\n{system.strip()}" if system and system.strip() else base_system

        contents = _to_gemini_contents(conversation, history, task)

        if force_final:
            prompt = (
                "위 데이터에만 근거해 핵심을 간결하고 자연스럽게 답하세요(질문과 같은 언어로). "
                "수치는 단위·기간과 함께 제시하고, 출처는 기관 이름(예: OpenDART, SEC EDGAR)으로 자연스럽게 언급하세요. "
                "근거가 된 출처는 해당 문장 끝에 [1], [2]처럼 등장 순서대로 번호를 붙여 인용하세요. "
                "원문 링크(URL)는 본문에 직접 쓰지 마세요 — [n] 번호만 쓰고, 링크는 출처 카드에 표시됩니다. "
                "내부 도구·함수 이름이나 코드 식별자(예: opendart__income_statements)는 절대 노출하지 마세요. "
                "가격 예측이나 매수/매도 의견은 금지하며, 별도의 면책 문구는 덧붙이지 마세요."
            )
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=prompt)]))
            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.2,
            )
            resp = await asyncio.to_thread(self._client.models.generate_content, model=self.model, contents=contents, config=config)
            text_val = _get_text_from_response(resp)
            logger.info("force_final response candidate content parts: %s", resp.candidates[0].content.parts if resp.candidates else None)
            return Decision(final=text_val)

        decls = [
            types.FunctionDeclaration(name=t["name"], description=t["description"], parameters=_schema(t))
            for t in tools.values()
        ]
        
        config = types.GenerateContentConfig(
            tools=[types.Tool(function_declarations=decls)],
            system_instruction=system_instruction,
        )

        resp = await asyncio.to_thread(self._client.models.generate_content, model=self.model, contents=contents, config=config)
        calls = getattr(resp, "function_calls", None)
        if calls:
            call = calls[0]
            thought_sig = None
            if resp.candidates and resp.candidates[0].content and resp.candidates[0].content.parts:
                for part in resp.candidates[0].content.parts:
                    if part.function_call and part.function_call.name == call.name:
                        thought_sig = part.thought_signature
                        break
            return Decision(tool=call.name, args=dict(call.args or {}), thought_signature=thought_sig)
        return Decision(final=_get_text_from_response(resp))


def _to_gemini_contents(conversation: list | None, history: list, task: str):
    from google.genai import types

    out = []
    if conversation:
        for m in conversation:
            c = m.get("content")
            if not c:
                continue
            role = "model" if m.get("role") == "assistant" else "user"
            out.append(types.Content(role=role, parts=[types.Part.from_text(text=c)]))

    if not out:
        out.append(types.Content(role="user", parts=[types.Part.from_text(text=task)]))

    for dec, res in history:
        # Function Call
        if dec.thought_signature:
            model_part = types.Part(
                function_call=types.FunctionCall(
                    name=dec.tool,
                    args=dec.args or {}
                ),
                thought_signature=dec.thought_signature
            )
        else:
            model_part = types.Part.from_function_call(
                name=dec.tool,
                args=dec.args or {}
            )
        out.append(types.Content(role="model", parts=[model_part]))

        # Function Response
        response_data = res.get("data")
        if not isinstance(response_data, dict):
            response_data = {"result": response_data}

        tool_part = types.Part.from_function_response(
            name=dec.tool,
            response=response_data
        )
        out.append(types.Content(role="tool", parts=[tool_part]))

    return out


def _schema(tool: dict) -> dict:
    props, required = {}, []
    for p in tool.get("params", []):
        prop = {"type": p.get("type", "string").upper() if p.get("type") in ("integer", "number", "boolean") else "STRING"}
        if p.get("enum"):
            prop["enum"] = p["enum"]
        if p.get("description"):
            prop["description"] = p["description"]
        props[p["name"]] = prop
        if p.get("required"):
            required.append(p["name"])
    return {"type": "OBJECT", "properties": props, "required": required}


@cache
def _build_planner(backend: str, model: str):
    if backend == "stub":
        return StubPlanner()
    if backend == "gemini":
        return GeminiPlanner(model)
    raise ValueError(f"Unknown agent backend '{backend}'.")


def get_planner(backend: str | None = None):
    """Return the planner for ``backend`` (per-agent override), else the server default."""
    return _build_planner(backend or settings.llm_backend, settings.model)
