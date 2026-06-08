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
from services.engine.financials.models import FinancialsRecord
from services.engine.financials.repository import FinancialsRepository
from services.engine.financials.research import ResearchedFinancials, merge_financials
from services.engine.llm.router import LLMRouter, Tier
from services.engine.themes.models import SourceCreate, Theme
from services.engine.themes.repository import ThemeRepository

logger = logging.getLogger("valuegraph.engine.cve.chain_research")

Event = dict[str, Any]
DEEP_RESEARCH_EXTRACTOR = "deep-research"


def _has_financials(record: FinancialsRecord | None) -> bool:
    """A company is 'covered' once it has revenue on file (the CVE denominator) — enough
    to skip re-researching it in the chain pass; missing cost buckets still get tickets."""
    return record is not None and record.revenue is not None


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
ROLE: You are a supply-chain analyst with live-web research (Deep Research).
GOAL: Research the REAL supplier->customer trades AMONG the listed companies, plus financials
ONLY for the companies under FINANCIALS NEEDED. Output structured, fully-sourced data the
engine will cross-check from both ledgers.

GROUNDING (critical — you can browse, so do):
- Use Google Search and actually READ the page (URL context) before reporting any number.
- ONLY use companies from the KNOWN COMPANIES list, with their EXACT tickers.
- Every trade/financial figure MUST cite a real public page you retrieved (put it in
  "source_url"). NEVER invent numbers or URLs. Report only DISCLOSED figures — never forecast.
- If a relationship exists but you cannot find a number, still emit the trade with relation
  "{QUALITATIVE}" and value null (a known link with no figure is useful).
- Financials: report ONLY tickers in FINANCIALS NEEDED (others already have figures on file —
  do NOT re-research them). If that list is empty, return "financials": [].

TRADE "relation" is one of:
- "{SUPPLIER_SHARE}": % of the SUPPLIER's revenue from the customer (value=percent, unit "%")
- "{CUSTOMER_SHARE}": % of the CUSTOMER's costs from the supplier (value=percent, unit "%")
- "{ABSOLUTE}": an absolute trade value (value=amount, unit=currency e.g. "USD")
- "{QUALITATIVE}": a known relationship with no disclosed number (value=null)
For each trade, "quote" is the VERBATIM sentence from the page that states it.
Financials are in MILLIONS of each company's OWN reporting "currency" (ISO code) — do NOT
convert to USD.

OUTPUT FORMAT — after your research, end with EXACTLY ONE fenced JSON code block
(```json … ```) and nothing after it, in this shape:
{{
  "trades": [
    {{"supplier": "<ticker>", "customer": "<ticker>", "relation": "<one of the four>",
"value": number|null, "unit": "%"|"<currency>"|null,
"cost_bucket": "COGS"|"CAPEX"|"R&D"|"SG&A"|null,
"as_of": "YYYY-MM-DD", "source_url": "<real page>", "quote": "<verbatim sentence>"}}
  ],
  "financials": [
    {{"ticker": "<ticker>", "currency": "<ISO>", "revenue": number|null, "cogs": number|null,
"capex": number|null, "rnd": number|null, "sga": number|null, "as_of": "YYYY-MM-DD",
"source_url": "<real page>"}}
  ]
}}

EXAMPLE:
```json
{{"trades": [{{"supplier": "INTC", "customer": "HPQ", "relation": "{SUPPLIER_SHARE}",
"value": 21, "unit": "%", "cost_bucket": "COGS", "as_of": "2025-12-31",
"source_url": "https://www.intc.com/10-K", "quote": "HP represented 21% of our revenue"}}],
"financials": [{{"ticker": "HPQ", "currency": "USD", "revenue": 53000, "cogs": 43000,
"capex": null, "rnd": null, "sga": null, "as_of": "2025-10-31",
"source_url": "https://investor.hp.com/10-K"}}]}}
```
"""


def build_chain_research_prompt(
    theme: Theme,
    companies: Iterable[BlueprintCompany],
    financials_needed: Iterable[BlueprintCompany] | None = None,
) -> str:
    companies = list(companies)
    known = ", ".join(f"{c.ticker} ({c.name})" for c in companies)
    # None => research financials for everyone (back-compat); a list => only those tickers.
    needed = companies if financials_needed is None else list(financials_needed)
    needed_str = ", ".join(c.ticker for c in needed) if needed else "(none)"
    lines = [_INSTRUCTIONS, "", f"THEME: {theme.name}"]
    if theme.description:
        lines.append(f"DESCRIPTION: {theme.description}")
    lines.append(f"KNOWN COMPANIES (use only these tickers): {known}")
    lines.append(f"FINANCIALS NEEDED (report financials ONLY for these): {needed_str}")
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
    # Don't re-research financials a company already has on file (e.g. filled on the
    # Financials step) — only ask Deep Research for the ones still missing revenue.
    needed = [
        c
        for c in blueprint.companies
        if not _has_financials(financials_repo.get(c.ticker))
    ]
    skipped = len(blueprint.companies) - len(needed)
    if skipped:
        yield {
            "event": "research",
            "action": "Financials on file",
            "detail": f"reusing {skipped}, researching {len(needed)}",
        }
    prompt = build_chain_research_prompt(theme, blueprint.companies, needed)
    yield {"event": "prompt", "text": prompt, "chars": len(prompt)}
    logger.info(
        "chain_research.start theme=%s companies=%d financials_needed=%d (reuse %d)",
        theme.id,
        len(blueprint.companies),
        len(needed),
        skipped,
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
