"""Prompt construction for per-ticket Deep Research resolution.

A ticket names a missing, source-required figure (``metric``) for a company
(``target`` ticker, with ``reason``/blueprint context). We ask the Deep Research agent
to actually search and read the live web, then return a strict verdict: the figure with
a real cited URL when it exists, or a reason it could not be sourced. Mirrors the
grounding rules of ``blueprint/prompt.py`` — never invent a number or a URL.
"""

from __future__ import annotations

import json

from services.engine.blueprint.models import BlueprintCompany
from services.engine.tickets.models import Ticket

_INSTRUCTIONS = """\
You are a supply-chain research analyst for an investment-research tool. Resolve ONE \
required data point for ONE company by researching the live web. Find the figure and \
cite the exact public page you read it from, or report precisely why it cannot be sourced.

Grounding rules (critical):
- Use Google Search and actually READ the pages (URL context) before answering.
- A reported value MUST come from a real public page you retrieved and that loads RIGHT \
NOW — a company IR/investor page, a regulatory filing (DART/EDGAR/etc.), an exchange \
disclosure, or a reputable news/industry article. Put that exact URL in "source_url".
- NEVER invent, guess, or "reconstruct" a value or a URL. If you cannot find a real, \
working source, do NOT report a value — return the appropriate non-"found" verdict instead.
- Prefer the primary/original disclosure over aggregators.
- Do NOT forecast or extrapolate. Report only what is actually disclosed.

Choose exactly ONE verdict:
- "found"         — you found the figure AND a real source URL for it.
- "not_disclosed" — the company confirms it does NOT disclose this figure.
- "not_found"     — the figure does not appear to exist in any public source.
- "paywalled"     — the figure exists but only behind a paywall you cannot read.
- "ambiguous"     — the metric or the company relationship is too unclear to answer.

Output: after your research, end your reply with EXACTLY ONE fenced JSON code block \
(```json … ```) and nothing after it, in this shape:
{
  "verdict": "found",
  "value": "21% of revenue",          // the figure, as disclosed (required if found)
  "unit": "% of revenue",             // unit/basis, if applicable
  "as_of_date": "2024-12-31",         // YYYY-MM-DD the figure applies to (if found)
  "confidence": "high",               // high | medium | low
  "source_url": "https://… (a real page you actually retrieved)",  // required if found
  "source_publisher": "publisher / site name",
  "notes": "short explanation (e.g. why not found / which disclosure it came from)"
}
"""


def build_ticket_research_prompt(
    ticket: Ticket, company: BlueprintCompany | None = None
) -> str:
    """Prompt for the Deep Research agent to resolve one ticket's data point.

    ``company`` (matched from the blueprint by ticker) enriches the prompt with the
    company's name/role/products/country when available.
    """
    lines = [_INSTRUCTIONS, ""]
    if company is not None:
        lines.append(f"COMPANY: {company.name} ({ticket.target})")
        if company.country:
            lines.append(f"COUNTRY: {company.country}")
        if company.role:
            lines.append(f"ROLE IN CHAIN: {company.role}")
        if company.products:
            lines.append(f"PRODUCTS: {', '.join(company.products)}")
    else:
        lines.append(f"COMPANY (ticker): {ticket.target}")
    lines.append(f"DATA POINT TO FIND: {ticket.metric}")
    if ticket.reason:
        lines.append(f"CONTEXT: {ticket.reason}")
    if ticket.current_estimate:
        lines.append(
            "CURRENT ESTIMATE / CONSTRAINT (verify or refine): "
            + json.dumps(ticket.current_estimate)
        )
    return "\n".join(lines)
