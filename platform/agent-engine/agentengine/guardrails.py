"""Boundary guardrails — enforced before any agent run.

The platform serves **sourced facts**, not predictions or advice. Requests for
forecasts / price targets / buy-sell recommendations are refused (PRD: no
prediction/forecasting; not investment advice).
"""

from __future__ import annotations

import re

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


def check(task: str) -> str | None:
    """Return a refusal message if the task crosses the boundary, else None."""
    task = task or ""
    if _FORECAST_EN.search(task) or _FORECAST_KO.search(task):
        return (
            "가격 예측·전망이나 매수/매도 의견은 제공하지 않아요. "
            "대신 공시·재무·가격·뉴스 등 출처가 있는 사실을 찾아드릴 수 있어요. "
            "(This service provides sourced facts, not investment advice or price predictions.)"
        )
    return None
