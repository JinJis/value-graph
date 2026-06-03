"""S3: Derivation (VSCA math) — one trade, two ledgers, plus cost-bucket typing.

A trade A->C is the same dollar amount two ways (PRD §6.1):
  supplier:  trade_value = supplier_rev_share% / 100 * Revenue_A
  customer:  trade_value = customer_cost_share% / 100 * CostBucket_C
One disclosure yields trade_value; the complementary share is derived from the
counterpart's denominator. Worked shape: INTC discloses 21% of revenue from HPQ ->
trade_value = 0.21 * Rev_INTC -> ~= 9.5% of HPQ COGS.

Shares are percentages (0-100), matching the SUPPLIES / Claim schema (PRD §5).
Cost-bucket typing is rule-based here; an LLM classifier (LOW/MEDIUM) is a later
enhancement (PRD §6.3). No match -> None (ambiguous -> ticket downstream).
"""

from __future__ import annotations

from pydantic import BaseModel

_COST_BUCKETS = {"COGS", "CAPEX", "R&D", "SG&A"}

# product/role keyword -> cost bucket. Order matters (first match wins).
_COST_BUCKET_RULES: list[tuple[tuple[str, ...], str]] = [
    (("equipment", "tool", "lithography", "fab ", "machine", "capacity", "capex"), "CAPEX"),
    (("research", "r&d", "rnd", "intellectual property", " ip ", "license", "patent"), "R&D"),
    (("marketing", "advertis", "consulting", "software", "saas", "service", "logistics"), "SG&A"),
    (
        (
            "hbm", "memory", "dram", "nand", "wafer", "chip", "processor", "cpu", "gpu",
            "component", "substrate", "packaging", "material", "sensor", "display", "battery",
        ),
        "COGS",
    ),
]


class DerivedTrade(BaseModel):
    trade_value: float | None
    supplier_rev_share: float | None
    customer_cost_share: float | None
    cost_bucket: str | None
    basis: str | None  # "supplier" | "customer" | None


def assign_cost_bucket(product: str | None, hint: str | None = None) -> str | None:
    """Type the trade into a cost bucket. A valid hint wins; else product keyword rules."""
    if hint in _COST_BUCKETS:
        return hint
    text = f" {(product or '').lower()} "
    for keywords, bucket in _COST_BUCKET_RULES:
        if any(keyword in text for keyword in keywords):
            return bucket
    return None  # ambiguous


def derive_trade(
    *,
    product: str | None = None,
    cost_bucket_hint: str | None = None,
    supplier_rev_share: float | None = None,
    supplier_revenue: float | None = None,
    customer_cost_share: float | None = None,
    customer_cost_bucket_value: float | None = None,
) -> DerivedTrade:
    """Compute trade_value from whichever side is disclosed, then derive the other."""
    trade_value: float | None = None
    basis: str | None = None
    sup_share = supplier_rev_share
    cust_share = customer_cost_share

    if supplier_rev_share is not None and supplier_revenue is not None:
        trade_value = supplier_rev_share / 100 * supplier_revenue
        basis = "supplier"
    elif customer_cost_share is not None and customer_cost_bucket_value is not None:
        trade_value = customer_cost_share / 100 * customer_cost_bucket_value
        basis = "customer"

    if trade_value is not None:
        if cust_share is None and customer_cost_bucket_value:
            cust_share = 100 * trade_value / customer_cost_bucket_value
        if sup_share is None and supplier_revenue:
            sup_share = 100 * trade_value / supplier_revenue

    return DerivedTrade(
        trade_value=trade_value,
        supplier_rev_share=sup_share,
        customer_cost_share=cust_share,
        cost_bucket=assign_cost_bucket(product, cost_bucket_hint),
        basis=basis,
    )
