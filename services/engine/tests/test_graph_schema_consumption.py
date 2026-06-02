"""[M0-SCHEMA-03] The canonical graph_schema imports and works from a service.

Proves the AC "types import from a service" and exercises the SUPPLIES required-field
enforcement (PRD §5.3) through the shared package.
"""

from __future__ import annotations

from graph_schema import SuppliesEdge, validate_supplies


def _edge() -> SuppliesEdge:
    # Typed at construction: mypy enforces the required keys here.
    return {
        "supplier": "INTC",
        "customer": "HPQ",
        "confidence": "derived",
        "confidence_interval": {"low": 8.0, "high": 11.0},
        "as_of_date": "2026-03-31",
        "next_expected_update": "2026-08-15",
        "freshness": "fresh",
    }


def test_engine_can_validate_a_supplies_edge() -> None:
    assert validate_supplies(_edge()) == []


def test_engine_rejects_supplies_missing_provenance() -> None:
    edge = dict(_edge())
    del edge["as_of_date"]  # a PRD §5.3 figure is missing -> must be rejected
    assert validate_supplies(edge)
