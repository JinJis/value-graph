"""Guardrail copy — the refusal + disclaimer text shown when a request is restricted.

The refuse/allow DECISION is NOT here. It is a judgment about intent, so it is made by the
LLM in the first-pass intake (``agent.analyze_task``), which judges the user's request in
context and returns a confidence score — never keyword/regex matching (invariant #9). This
module only holds the user-facing strings the boundary uses when the intake says "restricted".
"""

from __future__ import annotations

DISCLAIMER = (
    "This service provides sourced data and analysis — not investment advice — and does not "
    "predict prices or returns."
)

REFUSAL = (
    "가격 예측·전망이나 매수/매도 의견은 제공하지 않아요. "
    "대신 공시·재무·가격·뉴스 등 출처가 있는 사실을 찾아드릴 수 있어요. "
    "(This service provides sourced facts, not investment advice or price predictions.)"
)
