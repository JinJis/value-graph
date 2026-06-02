"""Validation tests for the canonical schema, Python side (PRD §5.3)."""

from __future__ import annotations

import pytest

from graph_schema import (
    ENTITY_NAMES,
    SUPPLIES_REQUIRED_FIELDS,
    SuppliesEdge,
    is_valid,
    validate,
    validate_supplies,
)


def _valid_supplies() -> dict[str, object]:
    return {
        "supplier": "INTC",
        "customer": "HPQ",
        "product_ref": "cpu",
        "trade_value": 1000,
        "currency": "USD",
        "supplier_rev_share": 21,
        "customer_cost_share": 9.5,
        "cost_bucket": "COGS",
        "confidence": "derived",
        "confidence_interval": {"low": 8, "high": 11},
        "as_of_date": "2026-03-31",
        "next_expected_update": "2026-08-15",
        "freshness": "fresh",
        "gap": False,
    }


def test_core_entities_present() -> None:
    for name in ("SuppliesEdge", "Company", "Claim", "Source"):
        assert name in ENTITY_NAMES


def test_valid_supplies_passes() -> None:
    assert validate_supplies(_valid_supplies()) == []
    assert is_valid("SuppliesEdge", _valid_supplies())


@pytest.mark.parametrize("field", SUPPLIES_REQUIRED_FIELDS)
def test_missing_required_supplies_field_is_rejected(field: str) -> None:
    edge = _valid_supplies()
    del edge[field]
    assert validate_supplies(edge), f"expected rejection when {field!r} is absent"


def test_supplies_required_matches_53() -> None:
    # PRD §5.3: every quantitative SUPPLIES figure carries these.
    assert {
        "as_of_date",
        "next_expected_update",
        "confidence",
        "confidence_interval",
        "freshness",
    } <= set(SUPPLIES_REQUIRED_FIELDS)


def test_typeddict_required_keys_match_canonical_schema() -> None:
    # The TypedDict surface must not drift from the canonical required list.
    assert SuppliesEdge.__required_keys__ == frozenset(SUPPLIES_REQUIRED_FIELDS)


def test_gap_edge_validates() -> None:
    edge = _valid_supplies()
    edge.update(
        trade_value=None,
        supplier_rev_share=None,
        customer_cost_share=None,
        confidence="estimated",
        freshness="gap",
        gap=True,
    )
    assert is_valid("SuppliesEdge", edge)


def test_out_of_enum_confidence_is_rejected() -> None:
    edge = _valid_supplies()
    edge["confidence"] = "guess"
    assert validate_supplies(edge)


def test_unknown_field_is_rejected() -> None:
    edge = _valid_supplies()
    edge["expected_upside"] = 0.2  # forecasting is out of scope and unschema'd
    assert validate_supplies(edge)


def test_unknown_entity_raises() -> None:
    with pytest.raises(KeyError):
        validate("NotAnEntity", {})
