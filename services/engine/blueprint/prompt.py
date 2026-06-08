"""Prompt construction for blueprint generation (DEEP tier)."""

from __future__ import annotations

from services.engine.blueprint.models import Blueprint, BlueprintContent
from services.engine.themes.models import Theme

_INSTRUCTIONS = """\
ROLE: You are a supply-chain analyst building a blueprint for an investment-research tool.
GOAL: Given a THEME, map the listed companies that compose its real supplier->customer
value chain — the PLAN of what to quantify later, not the numbers themselves.

CRITERIA:
- Coverage: at least 30 listed companies spanning at least 4 of KR, US, JP, CN, TW.
- Depth: include hidden 2nd/3rd-tier suppliers (materials, equipment, packaging, substrates),
  not just the obvious leaders.
- Identity: use REAL stock tickers; "country" MUST be an ISO-2 code (KR/US/JP/CN/TW/…).
- Honesty: do NOT invent trade values, shares, or forecasts. List only the structure and the
  "required_data_points" still to be sourced. One entry per company (no duplicates/aliases).

OUTPUT FORMAT — return ONLY a JSON object (no prose, no markdown fences), exactly:
{
  "companies": [
    {
      "ticker": "<real exchange ticker>",          // required
      "name": "<company name>",                      // required
      "country": "<ISO-2 code>",                     // required
      "exchange": "<listing venue or null>",
      "role": "<role in THIS chain>",                // required
      "products": ["<product/service into the chain>"],
      "required_data_points": ["<metric still needed to quantify its edges>"]
    }
  ],
  "relationship_types": ["SUPPLIES"],
  "notes": "<optional analyst notes or null>"
}

EXAMPLE (one company; return many):
{"companies": [{"ticker": "NVDA", "name": "NVIDIA", "country": "US", "exchange": "NASDAQ",
"role": "GPU / accelerator designer", "products": ["data-center GPUs"],
"required_data_points": ["revenue by customer", "HBM purchase volume"]}],
"relationship_types": ["SUPPLIES"], "notes": null}
"""


def build_prompt(theme: Theme, source_hints: list[str]) -> str:
    lines = [_INSTRUCTIONS, "", f"THEME: {theme.name}"]
    if theme.description:
        lines.append(f"DESCRIPTION: {theme.description}")
    if theme.seed_tickers:
        lines.append(f"SEED TICKERS: {', '.join(theme.seed_tickers)}")
    if source_hints:
        lines.append("ADDITIONAL CONTEXT (uploaded): " + "; ".join(source_hints))
    return "\n".join(lines)


# Instructions for the FIRST-PASS generation, run on the Deep Research agent. Unlike
# a plain LLM (which hallucinates plausible-but-dead URLs), Deep Research actually
# searches and reads the live web — so we DEMAND a real, retrieved citation per
# company and forbid invented links. The agent returns a long report; we ask it to
# end with exactly one fenced JSON block we can parse.
_RESEARCH_GENERATE_INSTRUCTIONS = """\
ROLE: You are a supply-chain analyst building a blueprint for an investment-research tool,
working with live-web research (Deep Research) — not from memory.
GOAL: Research the REAL supplier->customer value chain for the THEME and output the listed
companies that compose it, each backed by a real citation.

GROUNDING (critical — you can actually browse, so do):
- Use Google Search and actually READ the page (URL context) before listing a company.
- Every company MUST cite a real public page you retrieved that loads RIGHT NOW — a company
  IR/investor page, a regulatory filing (DART/EDGAR/TDnet/…), an exchange listing, or a
  reputable news/industry article. Put that exact URL in "source_url".
- NEVER invent, guess, or "reconstruct" a URL. If you cannot find a real, working source for
  a company, LEAVE IT OUT rather than fabricate a citation. Prefer primary over aggregators.

COVERAGE & IDENTITY:
- At least 30 listed companies spanning at least 4 of KR, US, JP, CN, TW.
- Include hidden 2nd/3rd-tier suppliers (materials, equipment, packaging, substrates).
- Use REAL stock tickers; "country" MUST be an ISO-2 code.
- Do NOT invent trade values or forecasts — only the structure + "required_data_points".

OUTPUT FORMAT — after your research, end your reply with EXACTLY ONE fenced JSON code block
(```json … ```) and nothing after it, in this shape:
{
  "companies": [
    {
      "ticker": "<real ticker>", "name": "<company>", "country": "<ISO-2>",
      "exchange": "<venue or null>", "role": "<role in chain>",
      "products": ["<product/service>"],
      "required_data_points": ["<metric still to source>"],
      "source_url": "<a real page you actually retrieved>",   // required
      "source_publisher": "<publisher / site name or null>"
    }
  ],
  "relationship_types": ["SUPPLIES"],
  "notes": "<optional analyst notes or null>"
}

EXAMPLE (one company; return many):
```json
{"companies": [{"ticker": "NVDA", "name": "NVIDIA", "country": "US", "exchange": "NASDAQ",
"role": "GPU / accelerator designer", "products": ["data-center GPUs"],
"required_data_points": ["revenue by customer", "HBM purchase volume"],
"source_url": "https://investor.nvidia.com/financial-info/financial-reports/",
"source_publisher": "NVIDIA IR"}], "relationship_types": ["SUPPLIES"], "notes": null}
```
"""


def build_research_generate_prompt(theme: Theme, source_hints: list[str]) -> str:
    """Prompt for the Deep Research first-pass generation (cited companies)."""
    lines = [_RESEARCH_GENERATE_INSTRUCTIONS, "", f"THEME: {theme.name}"]
    if theme.description:
        lines.append(f"DESCRIPTION: {theme.description}")
    if theme.seed_tickers:
        lines.append(f"SEED TICKERS: {', '.join(theme.seed_tickers)}")
    if source_hints:
        lines.append("ADDITIONAL CONTEXT (uploaded): " + "; ".join(source_hints))
    return "\n".join(lines)


_REFINE_INSTRUCTIONS = """\
ROLE: You are a supply-chain analyst improving an EXISTING theme blueprint (below).
GOAL: Return a better, complete blueprint in the SAME schema — never a partial diff.

CRITERIA:
- Expand hidden 2nd/3rd-tier vendors (materials, equipment, packaging, substrates).
- De-duplicate: exactly one entry per company (merge aliases / dual listings).
- Fill missing fields (exchange, products, required_data_points) where you can.
- "country" MUST be an ISO-2 code. Do NOT invent trade values, shares, or forecasts.
- If nothing can be improved, return the blueprint UNCHANGED.

OUTPUT FORMAT — return ONLY the FULL updated JSON object, same shape as the input:
{"companies": [ {ticker, name, country, exchange, role, products, required_data_points} ],
 "relationship_types": ["SUPPLIES"], "notes": "<or null>"}
"""


_DISCOVERY_INSTRUCTIONS = """\
ROLE: You are doing broad, worldwide constituent discovery for a supply-chain theme.
GOAL: Find ADDITIONAL listed companies in the theme's value chain that are NOT already
known — especially hidden 2nd/3rd-tier suppliers across KR, US, JP, CN, TW (and beyond).

CRITERIA:
- Return only companies not in the ALREADY KNOWN list; do not just repeat them.
- Every company MUST cite a real public web source it was found in ("source_url").
- Use REAL tickers; "country" MUST be an ISO-2 code. No invented trade values or forecasts.

OUTPUT FORMAT — return ONLY a JSON object, exactly:
{
  "companies": [
    {
      "ticker": "<real ticker>", "name": "<company>", "country": "<ISO-2>",
      "exchange": "<venue or null>", "role": "<role in chain>",
      "products": ["<product/service>"], "required_data_points": ["<metric to source>"],
      "source_url": "<real public page>",                    // required
      "source_publisher": "<publisher / site name or null>"
    }
  ]
}

EXAMPLE (one company; return many):
{"companies": [{"ticker": "6857.T", "name": "Advantest", "country": "JP", "exchange": "TSE",
"role": "ATE / test equipment", "products": ["SoC testers"],
"required_data_points": ["revenue by customer"],
"source_url": "https://www.advantest.com/investors", "source_publisher": "Advantest IR"}]}
"""


def build_discovery_prompt(theme: Theme, known_tickers: list[str]) -> str:
    return (
        f"{_DISCOVERY_INSTRUCTIONS}\n\nTHEME: {theme.name}\n"
        f"ALREADY KNOWN (find ADDITIONAL, do not just repeat): {', '.join(known_tickers)}"
    )


def build_refine_prompt(theme: Theme, current: Blueprint) -> str:
    content = BlueprintContent(
        companies=current.companies,
        relationship_types=current.relationship_types,
        notes=current.notes,
    )
    return (
        f"{_REFINE_INSTRUCTIONS}\n\nTHEME: {theme.name}\n"
        f"CURRENT BLUEPRINT (round {current.version}):\n{content.model_dump_json(indent=2)}"
    )
