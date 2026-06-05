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
from services.engine.themes.models import Theme
from services.engine.tickets.models import Ticket

# One (ref, ticket, matched blueprint company) to resolve.
ResearchItem = tuple[str, Ticket, BlueprintCompany | None]

_INSTRUCTIONS = """\
You are a supply-chain research analyst for an investment-research tool. You are given a \
THEME (a supplier->customer value chain) and a list of required data points — each is ONE \
metric for ONE company. Resolve EVERY data point by researching the live web: find the \
figure and cite the exact public page you read it from, or report precisely why it cannot \
be sourced.

Grounding rules (critical):
- Use Google Search and actually READ the pages (URL context) before answering.
- A reported value MUST come from a real public page you retrieved and that loads RIGHT \
NOW — a company IR/investor page, a regulatory filing (DART/EDGAR/etc.), an exchange \
disclosure, or a reputable news/industry article. Put that exact URL in "source_url".
- NEVER invent, guess, or "reconstruct" a value or a URL. If you cannot find a real, \
working source, do NOT report a value — return the appropriate non-"found" verdict instead.
- Prefer the primary/original disclosure over aggregators.
- Do NOT forecast or extrapolate. Report only what is actually disclosed.
- Use the theme + value-chain context to disambiguate the company relationship the metric \
refers to (e.g. which customer/supplier, which product line).

For EACH data point choose exactly ONE verdict:
- "found"         — you found the figure AND a real source URL for it.
- "not_disclosed" — the company confirms it does NOT disclose this figure.
- "not_found"     — the figure does not appear to exist in any public source.
- "paywalled"     — the figure exists but only behind a paywall you cannot read.
- "ambiguous"     — the metric or the company relationship is too unclear to answer.

Output: after your research, end your reply with EXACTLY ONE fenced JSON code block \
(```json … ```) and nothing after it. Return ONE result per data point, echoing its "ref", \
and do not omit any ref:
{
  "results": [
    {
      "ref": "T1",
      "verdict": "found",
      "value": "21% of revenue",       // the figure, as disclosed (required if found)
      "unit": "% of revenue",          // unit/basis, if applicable
      "as_of_date": "2024-12-31",      // YYYY-MM-DD the figure applies to (if found)
      "confidence": "high",            // high | medium | low
      "source_url": "https://… (a real page you actually retrieved)",  // required if found
      "source_publisher": "publisher / site name",
      "notes": "short explanation (e.g. why not found / which disclosure it came from)"
    }
  ]
}
"""


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
    lines = [_INSTRUCTIONS, "", "THEME CONTEXT:", f"THEME: {theme.name}"]
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
