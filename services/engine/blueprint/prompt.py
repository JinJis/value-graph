"""Prompt construction for blueprint generation (DEEP tier)."""

from __future__ import annotations

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
