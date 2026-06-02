"""Prompt construction for blueprint generation (DEEP tier)."""

from __future__ import annotations

from services.engine.blueprint.models import Blueprint, BlueprintContent
from services.engine.themes.models import Theme

_INSTRUCTIONS = """\
You are a supply-chain analyst building a blueprint for an investment-research \
tool. Given a theme, produce the plan of what is needed to map the theme's real \
supplier->customer value chain.

Return ONLY a JSON object (no prose, no markdown fences) with this shape:
{
  "companies": [
    {
      "ticker": "NVDA",
      "name": "NVIDIA",
      "country": "US",            // ISO-2 code; cover KR, US, JP, CN, TW
      "exchange": "NASDAQ",
      "role": "GPU / accelerator designer",
      "products": ["data-center GPUs"],
      "required_data_points": ["revenue by customer", "HBM purchase volume"]
    }
  ],
  "relationship_types": ["SUPPLIES"],
  "notes": "optional analyst notes"
}

Requirements:
- List at least 30 listed companies spanning at least 4 of: KR, US, JP, CN, TW.
- Include 2nd/3rd-tier suppliers (materials, equipment, packaging), not just the \
obvious names.
- "country" MUST be an ISO-2 code. Use real stock tickers where possible.
- Do NOT invent trade values or forecasts — only the structure and the data points \
that still need to be sourced.
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


_REFINE_INSTRUCTIONS = """\
Below is the CURRENT blueprint for a theme. Refine it:
- expand hidden / 2nd- and 3rd-tier vendors (materials, equipment, packaging, substrates);
- de-duplicate companies (exactly one entry per company; merge aliases);
- fill missing fields (exchange, products, required_data_points).

Return ONLY the FULL updated JSON object in the SAME schema as the input (companies, \
relationship_types, notes). Country MUST be an ISO-2 code. Do not invent trade values \
or forecasts. If nothing can be improved, return the blueprint unchanged.
"""


_DISCOVERY_INSTRUCTIONS = """\
You are doing broad, worldwide constituent discovery for a supply-chain theme. Find \
ADDITIONAL listed companies in the theme's value chain that are not already known — \
especially hidden 2nd- and 3rd-tier suppliers across KR, US, JP, CN, TW (and beyond).

Every company you return MUST cite a public web source it was found in. Return ONLY a \
JSON object:
{
  "companies": [
    {
      "ticker": "6857.T",
      "name": "Advantest",
      "country": "JP",
      "exchange": "TSE",
      "role": "ATE / test equipment",
      "products": ["SoC testers"],
      "required_data_points": ["revenue by customer"],
      "source_url": "https://...",
      "source_publisher": "optional publisher/site"
    }
  ]
}
Country MUST be an ISO-2 code. Do not invent trade values or forecasts.
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
