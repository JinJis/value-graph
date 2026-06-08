"""Deep Research the supply chain into structured CVE inputs.

Blueprint discovery finds the *companies*; this pass researches the actual data the graph
needs: supplier->customer trades (with values + citations) and each company's financials.
It persists a Source per citation, the trades as CVE :class:`Claim` objects, and the
financials into the financials store — then a CVE run seeded with these claims builds a
real, cited graph (gaps auto-ticket downstream). Reuses the Deep Research streaming +
JSON-parsing machinery (same as blueprint generation / ticket research).
"""

from __future__ import annotations

import logging
from collections.abc import Generator, Iterable
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from services.engine.blueprint.generate import BlueprintParseError, _extract_json
from services.engine.blueprint.models import BlueprintCompany, BlueprintRecord
from services.engine.blueprint.stream import _research_stream
from services.engine.cve.extract import (
    ABSOLUTE,
    CUSTOMER_SHARE,
    QUALITATIVE,
    SUPPLIER_SHARE,
    Claim,
)
from services.engine.financials.repository import FinancialsRepository
from services.engine.financials.research import ResearchedFinancials, merge_financials
from services.engine.llm.router import LLMRouter, Tier
from services.engine.themes.models import SourceCreate, Theme
from services.engine.themes.repository import ThemeRepository

logger = logging.getLogger("valuegraph.engine.cve.chain_research")

Event = dict[str, Any]
DEEP_RESEARCH_EXTRACTOR = "deep-research"


class ResearchedTrade(BaseModel):
    supplier: str
    customer: str
    relation: str = QUALITATIVE
    value: float | None = None
    unit: str | None = None
    cost_bucket: str | None = None
    as_of: str | None = None
    source_url: str | None = None
    quote: str | None = None


class ChainResearch(BaseModel):
    trades: list[ResearchedTrade] = Field(default_factory=list)
    financials: list[ResearchedFinancials] = Field(default_factory=list)


_INSTRUCTIONS = f"""\
You are a supply-chain analyst. Using the live web, research the REAL supplier->customer \
trades AMONG the listed companies, and each company's latest financials. Output structured \
data the engine will cross-check — every number must be sourced.

Grounding rules (critical):
- Use Google Search and actually READ the pages (URL context) before reporting a number.
- ONLY use companies from the KNOWN COMPANIES list (use their exact tickers).
- Every trade/financial figure MUST cite a real public page you retrieved (put it in \
"source_url"). NEVER invent numbers or URLs. If a relationship exists but you cannot find a \
number, still emit the trade with relation "{QUALITATIVE}" and value null.
- Do NOT forecast; report only disclosed figures.

Trade "relation" is one of:
- "{SUPPLIER_SHARE}": % of the SUPPLIER's revenue from the customer (value=percent, unit "%")
- "{CUSTOMER_SHARE}": % of the CUSTOMER's costs from the supplier (value=percent, unit "%")
- "{ABSOLUTE}": an absolute trade value (value=amount, unit=currency e.g. "USD")
- "{QUALITATIVE}": a known relationship with no number (value=null)

Output: after your research, end your reply with EXACTLY ONE fenced JSON code block \
(```json … ```) and nothing after it, in this shape:
{{
  "trades": [
    {{"supplier": "INTC", "customer": "HPQ", "relation": "{SUPPLIER_SHARE}", "value": 21, \
"unit": "%", "cost_bucket": "COGS", "as_of": "2025-12-31", \
"source_url": "https://… (a real page you retrieved)", "quote": "21% of revenue from HP"}}
  ],
  "financials": [
    {{"ticker": "HPQ", "revenue": 53000, "cogs": 43000, "capex": null, "rnd": null, \
"sga": null, "as_of": "2025-10-31", "source_url": "https://…"}}
  ]
}}
"""


def build_chain_research_prompt(
    theme: Theme, companies: Iterable[BlueprintCompany]
) -> str:
    known = ", ".join(f"{c.ticker} ({c.name})" for c in companies)
    lines = [_INSTRUCTIONS, "", f"THEME: {theme.name}"]
    if theme.description:
        lines.append(f"DESCRIPTION: {theme.description}")
    lines.append(f"KNOWN COMPANIES (use only these tickers): {known}")
    return "\n".join(lines)


def _parse_chain(buffer: str) -> ChainResearch:
    return ChainResearch.model_validate_json(_extract_json(buffer))


def _distinct_urls(content: ChainResearch) -> list[str]:
    seen: dict[str, None] = {}  # preserves order, dedupes
    for trade in content.trades:
        url = (trade.source_url or "").strip()
        if url:
            seen.setdefault(url, None)
    for fin in content.financials:
        url = (fin.source_url or "").strip()
        if url:
            seen.setdefault(url, None)
    return list(seen)


def research_chain_events(
    theme: Theme,
    blueprint: BlueprintRecord,
    theme_repo: ThemeRepository,
    financials_repo: FinancialsRepository,
    router: LLMRouter,
    *,
    today: str,
    tier: Tier = Tier.RESEARCH,
    attempts: int = 2,
) -> Generator[Event, None, list[Claim]]:
    """Stream a Deep Research chain pass; persist Sources/Claims/financials and RETURN the
    claims (via PEP 380 ``return``) so the caller can seed a CVE run with them."""
    model = router.model_for(tier)
    yield {"event": "model", "tier": tier.value, "model": model}
    yield {
        "event": "endpoint",
        "provider": "google-genai",
        "method": "interactions.create (deep-research)",
    }
    prompt = build_chain_research_prompt(theme, blueprint.companies)
    yield {"event": "prompt", "text": prompt, "chars": len(prompt)}
    logger.info(
        "chain_research.start theme=%s companies=%d", theme.id, len(blueprint.companies)
    )

    content: ChainResearch | None = None
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
            logger.warning("chain_research.stream_error theme=%s: %s", theme.id, exc)
            yield {"event": "error", "detail": f"{type(exc).__name__}: {exc}"}
            return []

        try:
            content = _parse_chain(buffer)
            yield {"event": "parse", "status": "ok"}
            break
        except (ValidationError, BlueprintParseError) as exc:
            last_error = str(exc)
            more = attempt + 1 < attempts
            yield {
                "event": "parse",
                "status": "retry" if more else "failed",
                "detail": last_error,
            }

    if content is None:
        yield {"event": "error", "detail": last_error or "chain research failed"}
        return []

    known = {c.ticker for c in blueprint.companies}

    # One Source per distinct citation URL -> url->id map.
    url_to_source: dict[str, str] = {}
    for url in _distinct_urls(content):
        record = theme_repo.add_source(theme.id, SourceCreate(type="report", url=url))
        url_to_source[url] = record.id

    # Financials (only known tickers; merge so research never clobbers existing buckets).
    fin_written = 0
    for fin in content.financials:
        if fin.ticker not in known:
            continue
        financials_repo.upsert(merge_financials(fin, financials_repo.get(fin.ticker)))
        fin_written += 1

    # Trades -> CVE claims (a number cannot enter without a Source).
    claims: list[Claim] = []
    for trade in content.trades:
        if trade.supplier not in known or trade.customer not in known:
            continue
        url = (trade.source_url or "").strip()
        source_id = url_to_source.get(url)
        if source_id is None and trade.value is not None:
            continue  # a quantified trade with no usable source is dropped
        claims.append(
            Claim(
                relation=trade.relation,
                subject=trade.supplier,
                object=trade.customer,
                value=trade.value,
                unit=trade.unit,
                cost_bucket=trade.cost_bucket,
                as_of=trade.as_of or today,
                source_id=source_id or "",
                extracted_by=DEEP_RESEARCH_EXTRACTOR,
                text_span=trade.quote or f"{trade.supplier}->{trade.customer} {trade.relation}",
            )
        )

    logger.info(
        "chain_research.persisted theme=%s trades=%d financials=%d sources=%d",
        theme.id,
        len(claims),
        fin_written,
        len(url_to_source),
    )
    yield {
        "event": "researched",
        "trades": len(claims),
        "financials": fin_written,
        "sources": len(url_to_source),
    }
    return claims
