"""Enrich terse blueprint data points into detailed, researchable ticket briefs.

A blueprint's ``required_data_points`` are short ("revenue by customer"). For the Deep Research
agent to investigate well, each ticket's description should say precisely WHAT figure to find,
WHY it matters in the theme's supplier->customer chain, and WHERE to look. A cheap model
rewrites them in ONE batch call; if it's unavailable, a deterministic template still adds the
company/theme context. The ``metric`` (the dedup key) stays as the raw data point — only the
``reason`` (description) is enriched, so generation stays idempotent.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from pydantic import BaseModel, Field

from services.engine.blueprint.generate import _extract_json
from services.engine.blueprint.models import BlueprintCompany
from services.engine.llm.router import LLMRouter, Tier
from services.engine.prompts import registry
from services.engine.themes.models import Theme

logger = logging.getLogger("valuegraph.engine.tickets.enrich")

# One (ref, company, raw data-point) to write a research brief for.
EnrichItem = tuple[str, BlueprintCompany, str]


class EnrichedPoint(BaseModel):
    ref: str
    description: str


class _Enriched(BaseModel):
    points: list[EnrichedPoint] = Field(default_factory=list)


_ENRICH_INSTRUCTIONS = """\
ROLE: You are a research editor preparing data-collection tickets for a supply-chain analyst.
GOAL: Rewrite each terse DATA POINT into a precise, researchable brief a Deep Research agent
can act on — WHAT exact figure/disclosure to find, WHY it matters for the THEME's
supplier->customer value chain, and WHERE to look.

For EACH data point, write a "description" (1-3 sentences) that:
- names the exact figure/disclosure to find for THAT company (units/basis if relevant);
- says why it matters for the supplier->customer relationship in this theme;
- points to where it's typically disclosed (latest 10-K / annual report / IR deck / earnings
  call / exchange filing), preferring the MOST RECENT period (as of 2026 Q1).
Do NOT answer the data point or invent any figures — only describe what to research.

OUTPUT FORMAT — return ONLY this JSON (no prose, no fences), exactly one entry per ref:
{"points": [{"ref": "<the ref>", "description": "<the brief>"}]}

EXAMPLE (data point "revenue by customer" for NVIDIA):
{"points": [{"ref": "P1", "description": "Find NVIDIA's customer-concentration disclosure — \
the % of total revenue from each major customer (and any named >10% customers) for the latest \
reported period. It sizes NVIDIA's exposure to specific data-center buyers in the AI value \
chain. Look in the most recent 10-K (customer concentration note) and recent earnings calls."}]}
"""

_ENRICH_KEY = registry.register(
    "tickets.generate_enrich",
    "Tickets — data-point enrichment",
    "Rewrite terse blueprint data points into detailed, researchable ticket briefs (MEDIUM).",
    _ENRICH_INSTRUCTIONS,
)


def build_enrich_prompt(theme: Theme, items: Sequence[EnrichItem]) -> str:
    lines = [registry.get(_ENRICH_KEY), "", f"THEME: {theme.name}"]
    if theme.description:
        lines.append(f"DESCRIPTION: {theme.description}")
    lines.append("")
    lines.append('DATA POINTS (write one "description" per ref):')
    for ref, company, metric in items:
        head = f"[{ref}] COMPANY: {company.name} ({company.ticker})"
        if company.role:
            head += f" · {company.role}"
        lines.append(head)
        if company.products:
            lines.append(f"      PRODUCTS: {', '.join(company.products)}")
        lines.append(f"      DATA POINT: {metric}")
    return "\n".join(lines)


def enrich_descriptions(
    theme: Theme,
    items: Sequence[EnrichItem],
    router: LLMRouter,
    *,
    tier: Tier = Tier.MEDIUM,
) -> dict[str, str]:
    """One cheap-model call -> {ref: detailed description}. Returns {} on any failure so the
    caller falls back to the deterministic template (generation never depends on the LLM)."""
    if not items:
        return {}
    try:
        text = router.generate(tier, build_enrich_prompt(theme, items))
        parsed = _Enriched.model_validate_json(_extract_json(text))
    except Exception as exc:  # LLM/network/parse — fall back to the template
        logger.warning("tickets.enrich_failed theme=%s: %s", theme.id, exc)
        return {}
    return {p.ref: p.description.strip() for p in parsed.points if p.description.strip()}


def fallback_description(
    theme: Theme | None, company: BlueprintCompany, metric: str
) -> str:
    """A richer-than-before description built deterministically (no LLM)."""
    context = [
        b
        for b in (
            company.role,
            ", ".join(company.products) if company.products else "",
            company.country,
        )
        if b
    ]
    theme_name = theme.name if theme is not None else "this"
    brief = f"Find '{metric}' for {company.name} ({company.ticker})"
    if context:
        brief += f" — {'; '.join(context)}"
    return (
        f"{brief}. It quantifies {company.name}'s role in the '{theme_name}' "
        "supplier->customer value chain; look in the latest 10-K / annual report / IR "
        "disclosures / earnings transcripts (prefer the most recent period)."
    )
