"""Theme-aware cost-bucket classification (S3 typing), pluggable.

The cost BUCKETS (COGS/CAPEX/R&D/SG&A) are universal accounting categories — they do not
change per theme. What IS theme-specific is deciding which bucket a given product/service
falls into (a GPU is COGS to a server maker but the rule keywords are hardware-flavoured).
So classification is an injected service, not a hardcoded table:

    hint (if already a valid bucket)  ->  cheap offline keyword rules  ->  theme-aware LLM

This keeps the engine domain-agnostic: a new theme (pharma, autos, energy…) gets correct
typing from the LLM for products the keyword rules don't know, instead of silently
defaulting everything to COGS.
"""

from __future__ import annotations

import logging
from typing import Protocol

from services.engine.cve.derive import COST_BUCKETS, assign_cost_bucket
from services.engine.llm.router import LLMRouter, Tier
from services.engine.prompts import registry

logger = logging.getLogger("valuegraph.engine.cve.cost_bucket")


class CostBucketClassifier(Protocol):
    def classify(self, product: str | None, *, hint: str | None = None) -> str | None: ...


class RuleCostBucketClassifier:
    """Offline keyword rules only (the historical behaviour; cheap, theme-agnostic)."""

    def classify(self, product: str | None, *, hint: str | None = None) -> str | None:
        return assign_cost_bucket(product, hint)


_INSTRUCTIONS = """\
ROLE: You are an accounting classifier.
GOAL: Classify ONE purchased product/service into the cost bucket the BUYER books it under,
using the THEME for context (the same item can differ by industry).

BUCKETS (choose exactly one):
- COGS: goods/components/materials consumed in or resold as the buyer's product.
- CAPEX: durable equipment/tools/property that is capitalised (depreciated over years).
- R&D: research, intellectual property, technology licenses.
- SG&A: selling/general/admin — marketing, software/SaaS, services, logistics.

OUTPUT: reply with EXACTLY ONE token — COGS, CAPEX, R&D, or SG&A — and nothing else.

EXAMPLES:
- "EUV lithography machine" (chip theme) -> CAPEX
- "HBM memory stacks" (GPU theme) -> COGS
- "patent license" -> R&D
- "CRM software subscription" -> SG&A
"""

_COST_BUCKET_KEY = registry.register(
    "cve.cost_bucket",
    "CVE S3 — cost-bucket typing",
    "Classify a purchased product/service into COGS/CAPEX/R&D/SG&A for the buyer (LOW tier).",
    _INSTRUCTIONS,
)


def build_cost_bucket_prompt(theme: str, product: str) -> str:
    instructions = registry.get(_COST_BUCKET_KEY)
    return f'{instructions}\nTHEME: {theme}\nPRODUCT/SERVICE: "{product}"\nBUCKET:'


class LLMCostBucketClassifier:
    """hint -> cheap rules -> theme-aware LLM (LOW tier), cached per product."""

    def __init__(self, router: LLMRouter, *, theme: str, tier: Tier = Tier.LOW) -> None:
        self._router = router
        self._theme = theme
        self._tier = tier
        self._cache: dict[str, str | None] = {}

    def classify(self, product: str | None, *, hint: str | None = None) -> str | None:
        if hint in COST_BUCKETS:
            return hint
        rule = assign_cost_bucket(product, hint)  # cheap shortcut for known keywords
        if rule is not None:
            return rule
        if not product or not product.strip():
            return None
        key = product.strip().lower()
        if key not in self._cache:
            self._cache[key] = self._classify_llm(product)
        return self._cache[key]

    def _classify_llm(self, product: str) -> str | None:
        try:
            text = self._router.generate(self._tier, build_cost_bucket_prompt(self._theme, product))
        except Exception as exc:  # LLM/network — fall back to "unknown" (-> default/ticket)
            logger.warning("cost_bucket.llm_failed product=%r: %s", product, exc)
            return None
        upper = text.upper()
        # Check the distinctive buckets before COGS (which is the common default).
        for bucket in ("CAPEX", "R&D", "SG&A", "COGS"):
            if bucket in upper:
                return bucket
        return None
