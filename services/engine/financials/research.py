"""Deep Research per-company financials (revenue + cost buckets) into the store.

Reuses the Deep Research streaming + JSON parsing machinery. Owns the researched-financials
model + merge so the CVE chain-research pass and this standalone "fill financials" action
share one shape (the CVE pass imports them from here).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from datetime import date
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from services.engine.blueprint.generate import (
    BlueprintParseError,
    _extract_json,
    parse_with_structuring,
)
from services.engine.blueprint.models import BlueprintCompany
from services.engine.blueprint.stream import _research_stream
from services.engine.financials.models import FinancialsUpsert
from services.engine.financials.repository import FinancialsRepository
from services.engine.llm.router import LLMRouter, Tier
from services.engine.prompts import registry
from services.engine.themes.models import Theme

logger = logging.getLogger("valuegraph.engine.financials.research")

Event = dict[str, Any]


class ResearchedFinancials(BaseModel):
    """One company's financials as returned by Deep Research (with a citation)."""

    ticker: str
    currency: str | None = None  # the company's OWN reporting currency (ISO, e.g. JPY)
    revenue: float | None = None
    cogs: float | None = None
    capex: float | None = None
    rnd: float | None = None
    sga: float | None = None
    as_of: str | None = None
    source_url: str | None = None


class FinancialsResearch(BaseModel):
    financials: list[ResearchedFinancials] = Field(default_factory=list)


def merge_financials(
    fin: ResearchedFinancials, existing: FinancialsUpsert | None
) -> FinancialsUpsert:
    """Fill only the buckets research found; keep any existing values otherwise."""

    def pick(field: str, value: float | None) -> float | None:
        if value is not None:
            return value
        return getattr(existing, field) if existing is not None else None

    return FinancialsUpsert(
        company_ticker=fin.ticker,
        currency=fin.currency or (existing.currency if existing is not None else None),
        revenue=pick("revenue", fin.revenue),
        cogs=pick("cogs", fin.cogs),
        capex=pick("capex", fin.capex),
        rnd=pick("rnd", fin.rnd),
        sga=pick("sga", fin.sga),
        as_of_date=date.fromisoformat(fin.as_of) if fin.as_of else None,
        source=fin.source_url,
    )


_INSTRUCTIONS = """\
ROLE: You are a financial-data analyst with live-web research (Deep Research).
GOAL: For EACH listed company, find its LATEST reported ANNUAL figures — revenue, COGS,
CAPEX, R&D, SG&A — from a primary source (10-K / annual report / IR page).

RECENCY (MOST IMPORTANT): Use the most recent reported period available as of 2026 Q1 (the
latest fiscal year, or the latest quarter if more current) — the newest figures are the most
important. Record the "as_of" date of the period you used.

UNITS (critical):
- Report each company in ITS OWN reporting currency (the one used in its financial
  statements — JPY for Tokyo Electron, KRW for Samsung, USD for NVIDIA), in MILLIONS of that
  currency, and put the 3-letter ISO code in "currency". Do NOT convert to USD.

GROUNDING:
- Use Google Search and actually READ the filing/IR page before reporting a number.
- Cite the real public page you retrieved in "source_url"; NEVER invent numbers or URLs.
- Omit (null) any figure you cannot source. Use ONLY the given tickers. No forecasts.

OUTPUT FORMAT — end your reply with EXACTLY ONE fenced JSON code block (```json … ```) and
nothing after it (all figures in MILLIONS of "currency"):
{
  "financials": [
    {"ticker": "<ticker>", "currency": "<ISO>", "revenue": number|null, "cogs": number|null,
     "capex": number|null, "rnd": number|null, "sga": number|null, "as_of": "YYYY-MM-DD",
     "source_url": "<a real page you retrieved>"}
  ]
}

EXAMPLE:
```json
{"financials": [{"ticker": "8035", "currency": "JPY", "revenue": 2400000, "cogs": 1500000,
"capex": 150000, "rnd": 180000, "sga": 300000, "as_of": "2025-03-31",
"source_url": "https://www.tel.com/ir/library/annual/"}]}
```
"""

_FINANCIALS_KEY = registry.register(
    "financials.research",
    "Financials — Deep Research",
    "Research each company's latest annual financials in its native currency (RESEARCH).",
    _INSTRUCTIONS,
)


def build_financials_prompt(theme_name: str, companies: Iterable[BlueprintCompany]) -> str:
    listed = ", ".join(f"{c.ticker} ({c.name})" for c in companies)
    return f"{registry.get(_FINANCIALS_KEY)}\nTHEME: {theme_name}\nCOMPANIES: {listed}"


def research_financials_events(
    theme: Theme,
    companies: list[BlueprintCompany],
    financials_repo: FinancialsRepository,
    router: LLMRouter,
    *,
    tier: Tier = Tier.RESEARCH,
    attempts: int = 2,
) -> Iterator[Event]:
    """Deep Research the companies' financials and upsert them, streaming progress."""
    model = router.model_for(tier)
    yield {"event": "model", "tier": tier.value, "model": model}
    yield {
        "event": "endpoint",
        "provider": "google-genai",
        "method": "interactions.create (deep-research)",
    }
    prompt = build_financials_prompt(theme.name, companies)
    yield {"event": "prompt", "text": prompt, "chars": len(prompt)}
    logger.info("financials.research theme=%s companies=%d", theme.id, len(companies))

    content: FinancialsResearch | None = None
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
                lambda t: FinancialsResearch.model_validate_json(_extract_json(t)),
                shape=registry.get(_FINANCIALS_KEY),
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
        yield {"event": "error", "detail": last_error or "financials research failed"}
        return

    known = {c.ticker for c in companies}
    filled = 0
    for fin in content.financials:
        if fin.ticker not in known:
            continue
        record = financials_repo.upsert(merge_financials(fin, financials_repo.get(fin.ticker)))
        filled += 1
        yield {
            "event": "filled",
            "ticker": record.company_ticker,
            "currency": record.currency,
            "revenue": record.revenue,
            "cogs": record.cogs,
            "capex": record.capex,
            "rnd": record.rnd,
            "sga": record.sga,
            "as_of_date": record.as_of_date.isoformat() if record.as_of_date else None,
            "source": record.source,
        }
    logger.info("financials.research.done theme=%s filled=%d", theme.id, filled)
    yield {"event": "done", "filled": filled}
