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

_FORECAST = re.compile(
    r"\b(predict|forecast|price target|target price|will\s+\w+\s+(go up|rise|fall|drop|increase|decrease)"
    r"|should i (buy|sell)|worth buying|worth selling|guarantee|to the moon)\b",
    re.IGNORECASE,
)


def check(task: str) -> str | None:
    """Return a refusal message if the task crosses the boundary, else None."""
    if _FORECAST.search(task or ""):
        return (
            "I can't provide price predictions, forecasts, or buy/sell recommendations. "
            + DISCLAIMER
            + " I can pull sourced facts (filings, financials, prices, news, disclosures) instead."
        )
    return None
