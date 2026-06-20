"""Planners: decide which tool to call (or finalize) given the task + tools.

* StubPlanner — deterministic keyword routing (dev/CI, no LLM). Calls one tool
  then summarizes. Lets the loop + provenance + guardrails be tested with no key.
* GeminiPlanner — real LLM (Gemini function calling), lazily imported.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import cache

from agentengine.config import settings

# Routing brain + Gemini serialization live in siblings; re-exported here so
# existing imports (agent.py, chat.py, tests) keep resolving them via this module.
from agentengine.routing import (  # noqa: F401
    _args_for,
    _callable,
    _infer_bank,
    _keyword_candidates,
    _market_of,
    _market_ok,
    _needs_ticker,
    _no_tool_message,
    _summarize,
    _ticker_fallback,
    _user_text,
    resolve_ticker,
)
from agentengine.gemini_io import (  # noqa: F401
    _get_text_from_response,
    _schema,
    _to_gemini_contents,
)

logger = logging.getLogger(__name__)


@dataclass
class Decision:
    tool: str | None = None
    args: dict | None = None
    final: str | None = None
    thought_signature: bytes | None = None


class StubPlanner:
    async def plan(self, task: str, tools: dict, history: list, system: str | None = None,
                   conversation: list | None = None, sources: str | None = None,
                   force_final: bool = False) -> Decision:
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


class GeminiPlanner:
    """Real Gemini planner (function calling). Untested without GOOGLE_API_KEY."""

    def __init__(self, model: str) -> None:
        from google import genai

        self._genai = genai
        self._client = genai.Client()
        self.model = model

    async def plan(self, task: str, tools: dict, history: list, system: str | None = None,
                   conversation: list | None = None, force_final: bool = False,
                   sources: str | None = None) -> Decision:
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
            "When you write the final answer, anchor each claim with an inline [n] marker that refers to "
            "the numbered source list provided below; use ONLY those exact numbers and never renumber.\n"
            "Never predict prices or give buy/sell advice; this is not investment advice."
        )

        system_instruction = f"{base_system}\n\n{system.strip()}" if system and system.strip() else base_system
        if sources:
            # the authoritative numbering — the model must cite with these exact [n].
            system_instruction += (
                "\n\nSources (cite ONLY with these exact bracketed numbers; do not invent or reorder):\n"
                + sources
            )

        contents = _to_gemini_contents(conversation, history, task)

        if force_final:
            prompt = (
                "위 데이터에만 근거해 핵심을 간결하고 자연스럽게 답하세요(질문과 같은 언어로). "
                "수치는 단위·기간과 함께 제시하고, 출처는 기관 이름(예: OpenDART, SEC EDGAR)으로 자연스럽게 언급하세요. "
                "근거가 된 출처는 문장 끝에 [n] 번호로 인용하되, 시스템 지침의 'Sources' 목록에 있는 "
                "정확한 번호만 사용하고 새 번호를 만들거나 순서를 바꾸지 마세요. "
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
