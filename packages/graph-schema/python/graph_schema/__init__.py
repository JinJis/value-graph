"""ValueGraph knowledge-graph schema — Python surface (PRD §5).

The canonical definition is the JSON Schema at ``packages/graph-schema/schema/
valuegraph.schema.json`` — the same file the TS package consumes. This module loads
it and exposes:

* ``TypedDict`` types for every node/edge (a typed surface for the services), and
* canonical-schema-driven validators (``validate`` / ``is_valid`` / ``validate_supplies``).

Because the validators read the canonical JSON, the TS and Python sides cannot drift.
"""

# NOTE: deliberately NOT using `from __future__ import annotations` — TypedDict's
# runtime `__required_keys__` (asserted against the canonical schema in the tests)
# can only see `Required[...]` markers when annotations are real objects, not PEP-563
# strings.
import json
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal, Required, TypedDict

from jsonschema import Draft202012Validator

__all__ = [
    "SCHEMA",
    "ENTITY_NAMES",
    "SUPPLIES_REQUIRED_FIELDS",
    "ConfidenceTier",
    "Freshness",
    "CostBucket",
    "SourceType",
    "VerificationStatus",
    "ConfidenceInterval",
    "DataQuality",
    "Theme",
    "Company",
    "Division",
    "Product",
    "Source",
    "Claim",
    "HasDivisionEdge",
    "ProducesEdge",
    "SuppliesEdge",
    "SupportsEdge",
    "SourcedFromEdge",
    "validate",
    "is_valid",
    "validate_supplies",
]

_SCHEMA_FILENAME = "valuegraph.schema.json"


def _load_schema() -> dict[str, Any]:
    # Installed wheel: schema is packaged next to this module (see force-include).
    packaged = files(__name__).joinpath(_SCHEMA_FILENAME)
    if packaged.is_file():
        data: dict[str, Any] = json.loads(packaged.read_text(encoding="utf-8"))
        return data
    # Editable/dev: read the canonical file from the repo tree (shared with TS).
    repo_copy = Path(__file__).resolve().parents[2] / "schema" / _SCHEMA_FILENAME
    data = json.loads(repo_copy.read_text(encoding="utf-8"))
    return data


SCHEMA: dict[str, Any] = _load_schema()
"""The canonical ValueGraph JSON Schema document (PRD §5)."""

_DEFS: dict[str, Any] = SCHEMA["$defs"]
ENTITY_NAMES: tuple[str, ...] = tuple(_DEFS.keys())
SUPPLIES_REQUIRED_FIELDS: tuple[str, ...] = tuple(_DEFS["SuppliesEdge"]["required"])

_VALIDATORS: dict[str, Draft202012Validator] = {
    name: Draft202012Validator(
        {"$id": SCHEMA["$id"], "$ref": f"#/$defs/{name}", "$defs": _DEFS}
    )
    for name in _DEFS
}


def validate(entity: str, data: object) -> list[str]:
    """Validate ``data`` against the named entity; return human-readable errors.

    An empty list means valid. Raises ``KeyError`` for an unknown entity name
    (no silent pass).
    """
    if entity not in _VALIDATORS:
        raise KeyError(f"Unknown ValueGraph schema entity: {entity!r}")
    validator = _VALIDATORS[entity]
    return [f"{error.json_path}: {error.message}" for error in validator.iter_errors(data)]


def is_valid(entity: str, data: object) -> bool:
    """Whether ``data`` satisfies the named entity schema."""
    return not validate(entity, data)


def validate_supplies(data: object) -> list[str]:
    """Validate a SUPPLIES edge (core v1 relationship; PRD §5.3 required figures)."""
    return validate("SuppliesEdge", data)


# --- Typed surface (mirrors the canonical schema; kept honest by tests) ---------

ConfidenceTier = Literal["verified", "derived", "estimated"]
Freshness = Literal["fresh", "aging", "stale", "gap"]
CostBucket = Literal["COGS", "CAPEX", "R&D", "SG&A"]
SourceType = Literal["filing", "IR", "report", "news", "interview"]
VerificationStatus = Literal["unverified", "verified", "disputed"]


class ConfidenceInterval(TypedDict):
    low: float
    high: float


class DataQuality(TypedDict):
    verified: float
    derived: float
    estimated: float
    gap: float


class Theme(TypedDict, total=False):
    name: Required[str]
    depth_max: int
    version: str
    published_at: str | None
    data_quality: DataQuality


class Company(TypedDict, total=False):
    ticker: Required[str]
    name: Required[str]
    country: str
    exchange: str
    market_cap: float | None
    price: float | None
    sector: str
    tier: int | None
    fiscal_calendar: str | None
    last_filing_date: str | None
    next_filing_estimate: str | None


class Division(TypedDict, total=False):
    name: Required[str]
    revenue_share: float | None
    parent_company: str | None


class Product(TypedDict, total=False):
    name: Required[str]
    category: str | None
    cost_bucket_hint: CostBucket | None


class Source(TypedDict, total=False):
    type: Required[SourceType]
    url: Required[str]
    publisher: str | None
    as_of_date: Required[str]
    language: str | None
    verification_status: VerificationStatus


class Claim(TypedDict, total=False):
    relation: Required[str]
    subject: Required[str]
    object: Required[str]
    value: float | None
    unit: str | None
    cost_bucket: CostBucket | None
    as_of: Required[str]
    source_id: Required[str]
    extracted_by: Required[str]
    text_span: Required[str]


class HasDivisionEdge(TypedDict):
    pass


class ProducesEdge(TypedDict, total=False):
    capacity: float | None
    yield_: float | None


class SuppliesEdge(TypedDict, total=False):
    supplier: Required[str]
    customer: Required[str]
    product_ref: str | None
    trade_value: float | None
    currency: str | None
    supplier_rev_share: float | None
    customer_cost_share: float | None
    cost_bucket: CostBucket | None
    confidence: Required[ConfidenceTier]
    confidence_interval: Required[ConfidenceInterval]
    as_of_date: Required[str]
    next_expected_update: Required[str]
    freshness: Required[Freshness]
    gap: bool


class SupportsEdge(TypedDict, total=False):
    weight: float | None
    agrees: Required[bool]


class SourcedFromEdge(TypedDict, total=False):
    extracted_value: float | str | None
