"""[M3-DER-03] S3 derivation: the two-ledger math and cost-bucket typing."""

from __future__ import annotations

import pytest

from services.engine.cve.derive import assign_cost_bucket, derive_trade


def test_intc_hpq_worked_example() -> None:
    # INTC discloses 21% of revenue from HPQ. Rev_INTC = 100, HPQ COGS = 221.
    derived = derive_trade(
        product="processors",
        supplier_rev_share=21,
        supplier_revenue=100,
        customer_cost_bucket_value=221,
    )
    assert derived.basis == "supplier"
    assert derived.trade_value == pytest.approx(21.0)
    assert derived.customer_cost_share == pytest.approx(9.5, abs=0.05)  # ~= 9.5% of HPQ COGS
    assert derived.cost_bucket == "COGS"


def test_customer_side_derives_supplier_share() -> None:
    # Same trade from the customer ledger: 9.5% of HPQ COGS (221) -> Rev_INTC = 100.
    derived = derive_trade(
        product="processors",
        customer_cost_share=21 / 221 * 100,
        customer_cost_bucket_value=221,
        supplier_revenue=100,
    )
    assert derived.basis == "customer"
    assert derived.trade_value == pytest.approx(21.0)
    assert derived.supplier_rev_share == pytest.approx(21.0, abs=0.05)
    assert derived.cost_bucket == "COGS"


def test_trade_value_none_without_a_denominator() -> None:
    derived = derive_trade(product="gpu", supplier_rev_share=21)  # no revenue
    assert derived.trade_value is None
    assert derived.basis is None
    assert derived.cost_bucket == "COGS"


@pytest.mark.parametrize(
    ("product", "expected"),
    [
        ("HBM stacks", "COGS"),
        ("data-center GPUs", "COGS"),
        ("EUV lithography equipment", "CAPEX"),
        ("fab tools", "CAPEX"),
        ("R&D collaboration", "R&D"),
        ("IP licensing", "R&D"),
        ("marketing services", "SG&A"),
        ("logistics", "SG&A"),
        ("widget", None),  # ambiguous -> ticket downstream
    ],
)
def test_cost_bucket_rules(product: str, expected: str | None) -> None:
    assert assign_cost_bucket(product) == expected


def test_cost_bucket_hint_wins() -> None:
    assert assign_cost_bucket("EUV lithography equipment", hint="COGS") == "COGS"
    assert assign_cost_bucket("anything", hint="CAPEX") == "CAPEX"
    assert assign_cost_bucket("anything", hint="BOGUS") is None  # invalid hint ignored
