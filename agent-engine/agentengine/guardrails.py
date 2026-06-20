"""Boundary guardrails — enforced before any agent run.

The platform serves **sourced facts**, not predictions or advice. Requests for
forecasts / price targets / buy-sell recommendations are refused (PRD: no
prediction/forecasting; not investment advice).
"""

from __future__ import annotations

import asyncio
import re
from pydantic import BaseModel
from agentengine.config import settings

from functools import cache

DISCLAIMER = (
    "This service provides sourced data and analysis — not investment advice — and does not "
    "predict prices or returns."
)

_FORECAST_EN = re.compile(
    r"\b(predict|forecast|price target|target price|will\s+\w+\s+(go up|rise|fall|drop|increase|decrease)"
    r"|should i (buy|sell)|worth buying|worth selling|guarantee|to the moon)\b",
    re.IGNORECASE,
)
# Korean forecast / buy-sell-advice cues (the agent's users are KR-localized).
_FORECAST_KO = re.compile(
    r"(오를까|오를지|오를까요|내릴까|내릴지|떨어질까|올라갈까|상승할까|하락할까"
    r"|사야\s*(할|되|하나|할까|함)|팔아야\s*(할|되|하나|할까|함)|살까|팔까"
    r"|매수\s*(할|하|해|추천|의견|타이밍|타점)|매도\s*(할|하|해|추천|의견|타이밍|타점)"
    r"|목표\s*주가|목표가|전망|예측|주가\s*예상|얼마까지\s*(오를|갈|떨어)"
    r"|투자\s*(추천|의견|조언)|추천\s*종목|유망\s*종목)"
)


class GuardrailResponse(BaseModel):
    violates: bool


_REFUSAL = (
    "가격 예측·전망이나 매수/매도 의견은 제공하지 않아요. "
    "대신 공시·재무·가격·뉴스 등 출처가 있는 사실을 찾아드릴 수 있어요. "
    "(This service provides sourced facts, not investment advice or price predictions.)"
)


class StubGuardrailer:
    async def check(self, task: str) -> str | None:
        task = task or ""
        if _FORECAST_EN.search(task) or _FORECAST_KO.search(task):
            return _REFUSAL
        return None


class GeminiGuardrailer:
    def __init__(self, model: str) -> None:
        from google import genai
        self._client = genai.Client()
        self.model = model

    async def check(self, task: str) -> str | None:
        task = task or ""
        from google import genai
        from google.genai import types

        prompt = (
            "You are a guardrail assistant for a financial information service.\n"
            "Your task is to analyze the user's input and determine if it asks for any of the following restricted topics:\n"
            "1. Price predictions, future forecasts, or direction bets (e.g., 'Will Apple stock go up?', 'Forecast Tesla earnings next year', 'Is the stock market going to crash?').\n"
            "2. Buy/sell advice, investment recommendation, or timing/buy points (e.g., 'Should I buy Nvidia?', 'Is Tesla worth buying?', 'Buy or sell AAPL?').\n"
            "3. Price targets (e.g., 'What is the price target for Microsoft?').\n\n"
            "You MUST allow requests for historical financial data, recent statements, macro data, public filings, news, and general company facts (e.g., 'What was Apple's revenue last year?', 'Fed interest rate trend', 'Samsung electronics recent earnings').\n\n"
            f"User Input: {task}\n\n"
            "Respond with a JSON object containing a single boolean field 'violates'."
        )
        try:
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=GuardrailResponse,
                temperature=0.0,
            )
            resp = await asyncio.to_thread(
                self._client.models.generate_content,
                model=self.model,
                contents=prompt,
                config=config,
            )
            import json
            data = json.loads(resp.text)
            if data.get("violates"):
                return _REFUSAL
        except Exception:
            # Fallback to regex check on any error to keep it safe
            if _FORECAST_EN.search(task) or _FORECAST_KO.search(task):
                return _REFUSAL
        return None


@cache
def _build_guardrailer(backend: str, model: str):
    if backend == "stub":
        return StubGuardrailer()
    if backend == "gemini":
        return GeminiGuardrailer(model)
    raise ValueError(f"Unknown agent backend '{backend}'.")


def get_guardrailer(backend: str | None = None):
    """Return the guardrailer for ``backend`` (per-agent override), else the server default."""
    return _build_guardrailer(backend or settings.llm_backend, settings.model)


