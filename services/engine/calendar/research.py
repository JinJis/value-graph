"""Deep Research a company's filing history -> infer cadence -> next_expected_update.

Mirrors the per-company financials research flow (same streaming + JSON-with-structuring
machinery). Deep Research returns each company's recent report/disclosure DATES; we infer the
cadence from the gaps (``schedule.estimate_next_filing``) and persist the projected next filing
via ``upsert_from_history`` — that's the seam the CVE score stage reads for next_expected_update.

No forecasting of fundamentals — only the *schedule* (when the next routine filing is due), which
is a public, deterministic cadence, not a prediction of any figure.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from services.engine.blueprint.generate import (
    BlueprintParseError,
    _extract_json,
    parse_with_structuring,
)
from services.engine.blueprint.identity import build_ticker_index, resolve_to_known
from services.engine.blueprint.models import BlueprintCompany
from services.engine.blueprint.stream import _research_stream
from services.engine.calendar.repository import CalendarRepository, upsert_from_history
from services.engine.llm.router import LLMRouter, Tier
from services.engine.prompts import registry
from services.engine.themes.models import Theme

logger = logging.getLogger("valuegraph.engine.calendar.research")

Event = dict[str, Any]


class ResearchedSchedule(BaseModel):
    """One company's filing history as returned by Deep Research (with a citation)."""

    # A numeric ticker may arrive as a JSON number — coerce to str so it doesn't drop.
    model_config = ConfigDict(coerce_numbers_to_str=True)
    ticker: str
    # Recent routine-filing dates (annual/quarterly report or equivalent disclosure), ISO.
    filing_dates: list[str] = Field(default_factory=list)
    fiscal_calendar: str | None = None  # e.g. "quarterly", "annual", "FY-Mar"
    source_url: str | None = None


class ScheduleResearch(BaseModel):
    schedules: list[ResearchedSchedule] = Field(default_factory=list)


def _parse_dates(values: list[str]) -> list[date]:
    out: list[date] = []
    for v in values:
        try:
            out.append(date.fromisoformat(v.strip()))
        except (ValueError, AttributeError):
            continue
    return out


_INSTRUCTIONS = """\
ROLE: You are a disclosure-calendar analyst with live-web research (Deep Research).
GOAL: For EACH listed company, find the DATES of its recent routine financial filings (the
last 4-8 annual or quarterly reports / equivalent regulatory disclosures), so we can learn its
filing cadence and project the next expected filing. This is a SCHEDULE, not a forecast of any
figure.

RECENCY (MOST IMPORTANT): Include the company's MOST RECENT filings available as of 2026 Q1 —
the newest dates matter most. List dates newest-first.

GROUNDING:
- Use Google Search and actually READ the IR/regulatory page (investor relations, EDGAR/DART/
  TDnet, exchange disclosure) before reporting dates. NEVER invent dates or URLs.
- Give the real period-end or filing date in ISO YYYY-MM-DD. Use ONLY the given tickers.
- State the cadence in "fiscal_calendar" (e.g. "quarterly", "annual", "FY-Mar"). Omit (null)
  anything you cannot source.

OUTPUT FORMAT — end your reply with EXACTLY ONE fenced JSON code block (```json … ```) and
nothing after it:
{
  "schedules": [
    {"ticker": "<ticker>", "filing_dates": ["YYYY-MM-DD", "YYYY-MM-DD", ...],
     "fiscal_calendar": "quarterly|annual|FY-<Mon>", "source_url": "<a real page you retrieved>"}
  ]
}

EXAMPLE:
```json
{"schedules": [{"ticker": "8035", "filing_dates": ["2025-10-30", "2025-07-31", "2025-04-30",
"2025-02-13"], "fiscal_calendar": "quarterly", "source_url": "https://www.tel.com/ir/library/"}]}
```
"""

_CALENDAR_KEY = registry.register(
    "calendar.research",
    "Disclosure Calendar — Deep Research",
    "Research each company's recent filing dates to infer its cadence + next filing (RESEARCH).",
    _INSTRUCTIONS,
)


def build_calendar_prompt(theme_name: str, companies: Iterable[BlueprintCompany]) -> str:
    listed = ", ".join(f"{c.ticker} ({c.name})" for c in companies)
    return f"{registry.get(_CALENDAR_KEY)}\nTHEME: {theme_name}\nCOMPANIES: {listed}"


def research_calendar_events(
    theme: Theme,
    companies: list[BlueprintCompany],
    calendar_repo: CalendarRepository,
    router: LLMRouter,
    *,
    tier: Tier = Tier.RESEARCH,
    attempts: int = 2,
    today: date | None = None,
) -> Iterator[Event]:
    """Deep Research the companies' filing history, infer cadence, and persist the projected
    next filing per company, streaming progress."""
    anchor = today or date.today()
    model = router.model_for(tier)
    yield {"event": "model", "tier": tier.value, "model": model}
    yield {
        "event": "endpoint",
        "provider": "google-genai",
        "method": "interactions.create (deep-research)",
    }
    prompt = build_calendar_prompt(theme.name, companies)
    yield {"event": "prompt", "text": prompt, "chars": len(prompt)}
    logger.info("calendar.research theme=%s companies=%d", theme.id, len(companies))

    content: ScheduleResearch | None = None
    last_error: str | None = None
    for attempt in range(attempts):
        nudge = "" if attempt == 0 else "\n\nEnd your reply with ONLY the fenced ```json block."
        yield {"event": "llm_start", "attempt": attempt + 1, "attempts": attempts}
        buffer = ""
        try:
            for ev in _research_stream(router, tier, prompt + nudge):
                if ev.get("event") == "chunk":
                    buffer += str(ev.get("text", ""))
                yield ev
        except Exception as exc:  # GeminiError, timeout, network
            yield {"event": "error", "detail": f"{type(exc).__name__}: {exc}"}
            return
        try:
            content = yield from parse_with_structuring(
                buffer,
                lambda t: ScheduleResearch.model_validate_json(_extract_json(t)),
                shape=registry.get(_CALENDAR_KEY),
                router=router,
            )
            yield {"event": "parse", "status": "ok"}
            break
        except (ValueError, ValidationError, BlueprintParseError) as exc:
            last_error = str(exc)
            more = attempt + 1 < attempts
            yield {
                "event": "parse",
                "status": "retry" if more else "failed",
                "detail": last_error,
            }

    if content is None:
        yield {"event": "error", "detail": last_error or "calendar research failed"}
        return

    index = build_ticker_index(companies)
    filled = 0
    for sched in content.schedules:
        ticker = resolve_to_known(sched.ticker, index)  # raw/name -> canonical blueprint ticker
        if ticker is None:
            continue
        history = _parse_dates(sched.filing_dates)
        if not history:
            # No dated filing we could parse -> can't infer a cadence; report it, don't guess.
            yield {"event": "skipped", "ticker": ticker, "reason": "no parseable filing dates"}
            continue
        entry = upsert_from_history(
            calendar_repo, ticker, history, today=anchor, source=sched.source_url
        )
        filled += 1
        yield {
            "event": "filled",
            "ticker": entry.company_ticker,
            "fiscal_calendar": entry.fiscal_calendar,
            "last_filing_date": entry.last_filing_date.isoformat()
            if entry.last_filing_date
            else None,
            "cadence_days": entry.cadence_days,
            "next_filing_estimate": entry.next_filing_estimate.isoformat()
            if entry.next_filing_estimate
            else None,
            "source": entry.source,
        }
    logger.info("calendar.research.done theme=%s filled=%d", theme.id, filled)
    yield {"event": "done", "filled": filled}
