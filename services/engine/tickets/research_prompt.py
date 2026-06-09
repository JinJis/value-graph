"""Prompt construction for batched per-ticket Deep Research resolution.

A ticket names a missing, source-required figure (``metric``) for a company
(``target`` ticker). We hand the Deep Research agent the THEME + value-chain context
plus EVERY selected ticket in one prompt, and ask it to resolve each independently and
return one result per ticket (keyed by a stable ``ref``). The agent must actually search
and read the live web and cite the exact page — never invent a number or a URL (mirrors
``blueprint/prompt.py``).
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from services.engine.blueprint.models import BlueprintCompany
from services.engine.prompts import registry
from services.engine.themes.models import Theme
from services.engine.tickets.models import Ticket

# One (ref, ticket, matched blueprint company) to resolve.
ResearchItem = tuple[str, Ticket, BlueprintCompany | None]

_INSTRUCTIONS = """\
ROLE: You are a supply-chain research analyst for an investment-research tool, with live-web
research (Deep Research).
GOAL: You are given a THEME (a supplier->customer value chain) and a list of required data
points — each ONE metric for ONE company. Resolve EVERY data point: either find the figure
and cite the exact public page you read it from, or report precisely why it cannot be sourced.

RECENCY (MOST IMPORTANT): Find the LATEST disclosed value available as of 2026 Q1 — the most
recent figure is the most important. Prefer the newest filing/quarter; if older and newer
values both exist, report the newest and put its date in "as_of_date".

GROUNDING (critical — you can browse, so do):
- Use Google Search and actually READ the page (URL context) before answering.
- A reported value MUST come from a real public page you retrieved that loads RIGHT NOW — a
  company IR page, a regulatory filing (DART/EDGAR/…), an exchange disclosure, or a reputable
  news/industry article. Put that exact URL in "source_url".
- NEVER invent, guess, or "reconstruct" a value or URL. If you can't find a real, working
  source, do NOT report a value — return the appropriate non-"found" verdict instead.
- Prefer primary disclosures over aggregators. Do NOT forecast — report only what is disclosed.
- Use the theme + value-chain context to disambiguate which relationship/product the metric
  refers to.

VERDICT — choose exactly ONE per data point:
- "found"         — you found the figure AND a real source URL for it.
- "not_disclosed" — the company confirms it does NOT disclose this figure.
- "not_found"     — the figure does not appear to exist in any public source.
- "paywalled"     — the figure exists but only behind a paywall you cannot read.
- "ambiguous"     — the metric or the company relationship is too unclear to answer.

OUTPUT FORMAT — after your research, end with EXACTLY ONE fenced JSON code block
(```json … ```) and nothing after it. Return ONE result per data point, ECHOING its "ref"
(omit none):
{
  "results": [
    {
      "ref": "<the ref given>",
      "verdict": "<one of the five above>",
      "value": "<the figure as disclosed>",   // required if found, else null
      "unit": "<unit/basis>",                  // e.g. "% of revenue", or null
      "as_of_date": "YYYY-MM-DD",              // the date it applies to, if found
      "confidence": "high"|"medium"|"low",
      "source_url": "<a real page you retrieved>",  // required if found, else null
      "source_publisher": "<publisher / site name or null>",
      "notes": "<short: which disclosure it came from, or why not found>"
    }
  ]
}

EXAMPLE:
```json
{"results": [{"ref": "T1", "verdict": "found", "value": "21% of revenue",
"unit": "% of revenue", "as_of_date": "2024-12-31", "confidence": "high",
"source_url": "https://investor.nvidia.com/10-K", "source_publisher": "NVIDIA IR",
"notes": "Customer concentration note in FY24 10-K"}]}
```
"""

_TICKET_RESEARCH_KEY = registry.register(
    "tickets.research",
    "Tickets — Deep Research resolution",
    "Resolve each selected ticket's data point on the Deep Research agent (RESEARCH).",
    _INSTRUCTIONS,
)


def _ticket_block(ref: str, ticket: Ticket, company: BlueprintCompany | None) -> str:
    lines: list[str] = []
    if company is not None:
        bits = [b for b in (company.country, company.role) if b]
        head = f"[{ref}] COMPANY: {company.name} ({ticket.target})"
        if bits:
            head += " · " + " · ".join(bits)
        lines.append(head)
        if company.products:
            lines.append(f"      PRODUCTS: {', '.join(company.products)}")
        if company.source_url:
            lines.append(f"      KNOWN SOURCE: {company.source_url}")
    else:
        lines.append(f"[{ref}] COMPANY (ticker): {ticket.target}")
    lines.append(f"      METRIC: {ticket.metric}")
    if ticket.reason:
        lines.append(f"      CONTEXT: {ticket.reason}")
    if ticket.current_estimate:
        lines.append(
            "      CURRENT ESTIMATE / CONSTRAINT (verify or refine): "
            + json.dumps(ticket.current_estimate)
        )
    return "\n".join(lines)


def build_ticket_research_batch_prompt(
    theme: Theme,
    items: Sequence[ResearchItem],
    *,
    relationship_types: Sequence[str] = (),
    notes: str | None = None,
) -> str:
    """Build one Deep Research prompt resolving every selected ticket, with theme +
    value-chain context shared across them."""
    lines = [registry.get(_TICKET_RESEARCH_KEY), "", "THEME CONTEXT:", f"THEME: {theme.name}"]
    if theme.description:
        lines.append(f"DESCRIPTION: {theme.description}")
    if theme.seed_tickers:
        lines.append(f"SEED TICKERS: {', '.join(theme.seed_tickers)}")
    if relationship_types:
        lines.append(f"VALUE-CHAIN RELATIONSHIPS: {', '.join(relationship_types)}")
    if notes:
        lines.append(f"BLUEPRINT NOTES: {notes}")
    lines.append("")
    lines.append('DATA POINTS TO RESOLVE (resolve EACH independently; echo its "ref"):')
    for ref, ticket, company in items:
        lines.append(_ticket_block(ref, ticket, company))
    return "\n".join(lines)
