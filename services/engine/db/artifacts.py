"""[M4-PERSIST-01] Map a CVE run's state into schema-valid, persistable graph artifacts.

A :class:`ThemeBuild` is one versioned snapshot of a theme's supply graph derived
from a CVE run (:class:`~services.engine.cve.pipeline.CVEState`):

- ``companies`` / ``edges`` / ``claims`` — graph-schema-valid ``Company`` /
  ``SuppliesEdge`` / ``Claim`` payloads (validated here; invalid ones never enter
  the graph — invariant "no number without a Source", and every figure carries
  source + as_of + next_update + confidence + interval).
- ``sources`` — provenance nodes keyed by ``source_id`` (the authoritative Source
  record lives in Postgres; the graph keeps a node + SOURCED_FROM links).
- ``gap_edges`` — edges that did NOT meet the SuppliesEdge schema (missing
  provenance, e.g. an estimated edge with no filing date). They are recorded, not
  dropped, so gaps are drawn (ghost edges) downstream, never hidden.

Curation of the *publishable* subset (completeness thresholds, filtering) is
M4-ASM-02; here we persist the full raw build.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from graph_schema import validate
from services.engine.cve.derive import derive_trade
from services.engine.cve.extract import ABSOLUTE, SUPPLIER_SHARE
from services.engine.cve.pipeline import CVEState, EdgeResult

# SuppliesEdge fields that must be present + non-null for a publishable edge.
_REQUIRED_EDGE_PROVENANCE = ("as_of_date", "next_expected_update")


class GapEdge(BaseModel):
    """An edge that exists but isn't yet a schema-valid SuppliesEdge (a drawn gap)."""

    supplier: str
    customer: str
    confidence: str
    freshness: str
    reason: str


class ThemeBuild(BaseModel):
    """One versioned snapshot of a theme's CVE-derived supply graph."""

    theme_id: str
    version: int
    created_at: datetime
    companies: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    claims: list[dict[str, Any]] = Field(default_factory=list)
    sources: dict[str, dict[str, Any]] = Field(default_factory=dict)  # source_id -> Source payload
    gap_edges: list[GapEdge] = Field(default_factory=list)
    # "supplier->customer" -> the Source(s) backing that edge's figures (PROV-02).
    edge_sources: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    # "supplier->customer" -> {reconciliation, claims} for the edge inspector (EDGE-03).
    edge_details: dict[str, dict[str, Any]] = Field(default_factory=dict)


_CLAIM_SUMMARY_FIELDS = (
    "relation",
    "value",
    "unit",
    "cost_bucket",
    "text_span",
    "source_id",
    "as_of",
)


def claim_summary(claim: dict[str, Any]) -> dict[str, Any]:
    return {k: claim.get(k) for k in _CLAIM_SUMMARY_FIELDS}


def edge_detail(edge: EdgeResult, edge_claims: list[dict[str, Any]]) -> dict[str, Any]:
    """Supporting claims + the reconciliation summary (point/interval/status/conflict)."""
    rec = edge.reconciled
    reconciliation = (
        None
        if rec is None
        else {
            "point": rec.point,
            "interval": {"low": rec.interval.low, "high": rec.interval.high},
            "n_sources": rec.n_sources,
            "status": rec.status,  # "reconciled" | "conflict"
            "reason": rec.reason,
        }
    )
    return {
        "reconciliation": reconciliation,
        "claims": [claim_summary(c) for c in edge_claims],
    }


def edge_source_refs(
    claims: list[dict[str, Any]], sources: dict[str, dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    """Per-edge Source references, derived from the claim->Source chain (PROV-02).

    Every figure on an edge traces to the Source(s) of the claims that produced it;
    each ref carries the link (url) + type + as_of so the Terminal can open the
    actual document. Bare reference sources contribute ``url=None`` (id only).
    """
    out: dict[str, list[dict[str, Any]]] = {}
    for claim in claims:
        key = f"{claim['subject']}->{claim['object']}"
        source_id = claim["source_id"]
        meta = sources.get(source_id, {})
        ref = {
            "source_id": source_id,
            "url": meta.get("url"),
            "type": meta.get("type"),
            "as_of_date": meta.get("as_of_date") or claim.get("as_of"),
        }
        refs = out.setdefault(key, [])
        if not any(r["source_id"] == source_id for r in refs):
            refs.append(ref)
    return out


def _edge_claims(edge: EdgeResult, claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for c in claims if c["subject"] == edge.supplier and c["object"] == edge.customer]


def _edge_economics(
    edge: EdgeResult,
    edge_claims: list[dict[str, Any]],
    financials: dict[str, dict[str, float]],
) -> tuple[float | None, float | None, str | None]:
    """Recover (trade_value, supplier_rev_share, cost_bucket) for an edge from its claims.

    Reuses the S3 two-ledger math (no duplicate derivation). Returns Nones when the
    complementary side can't be computed.
    """
    def _first_value(relation: str) -> float | None:
        values = (
            c["value"]
            for c in edge_claims
            if c["relation"] == relation and c["value"] is not None
        )
        return next(values, None)

    cost_bucket = next((c["cost_bucket"] for c in edge_claims if c.get("cost_bucket")), None)
    supplier_share = _first_value(SUPPLIER_SHARE)
    absolute = _first_value(ABSOLUTE)
    bucket_value = financials.get(edge.customer, {}).get(cost_bucket) if cost_bucket else None

    if supplier_share is not None:
        supplier_revenue = financials.get(edge.supplier, {}).get("revenue")
        derived = derive_trade(
            cost_bucket_hint=cost_bucket,
            supplier_rev_share=supplier_share,
            supplier_revenue=supplier_revenue,
            customer_cost_bucket_value=bucket_value,
        )
        return derived.trade_value, supplier_share, derived.cost_bucket
    if absolute is not None:
        return absolute, None, cost_bucket
    return None, None, cost_bucket


def _supplies_edge(
    edge: EdgeResult, edge_claims: list[dict[str, Any]], financials: dict[str, dict[str, float]]
) -> dict[str, Any]:
    assert edge.scored is not None and edge.reconciled is not None
    trade_value, supplier_rev_share, cost_bucket = _edge_economics(edge, edge_claims, financials)
    interval = edge.scored.confidence_interval
    return {
        "supplier": edge.supplier,
        "customer": edge.customer,
        "product_ref": None,
        "trade_value": trade_value,
        "currency": None,
        "supplier_rev_share": supplier_rev_share,
        # The reconciled metric is the customer-side share (the worked-example output).
        "customer_cost_share": edge.reconciled.point,
        "cost_bucket": cost_bucket,
        "confidence": edge.scored.confidence,
        "confidence_interval": {"low": interval.low, "high": interval.high},
        "as_of_date": edge.scored.as_of_date,
        "next_expected_update": edge.scored.next_expected_update,
        "freshness": edge.scored.freshness,
        "gap": edge.reconciled.status == "conflict" or edge.estimated,
    }


def build_from_cve(
    state: CVEState,
    *,
    version: int,
    sources: list[dict[str, Any]] | None = None,
    company_meta: dict[str, dict[str, Any]] | None = None,
    created_at: datetime | None = None,
) -> ThemeBuild:
    """Assemble a versioned :class:`ThemeBuild` from a finished CVE run state.

    ``sources`` (optional) are full Source records (each a graph-schema ``Source``
    plus an ``id``); when omitted, provenance nodes are built as bare ``{id}``
    references (the authoritative record stays in Postgres).

    ``company_meta`` (optional) maps a ticker to its blueprint identity
    (``{"name", "domain"}``) so the published node carries a real name + logo domain
    instead of the bare ticker.
    """
    claims = [c.model_dump(mode="json") for c in state.claims]
    valid_claims = [c for c in claims if not validate("Claim", c)]

    tickers: set[str] = set()
    edges: list[dict[str, Any]] = []
    gap_edges: list[GapEdge] = []
    edge_details: dict[str, dict[str, Any]] = {}
    for edge in state.edges.values():
        if edge.scored is None or edge.reconciled is None:
            continue
        tickers.update((edge.supplier, edge.customer))
        payload = _supplies_edge(edge, _edge_claims(edge, claims), state.financials)
        if validate("SuppliesEdge", payload):  # missing provenance -> a drawn gap, not dropped
            missing = [f for f in _REQUIRED_EDGE_PROVENANCE if not payload.get(f)]
            gap_edges.append(
                GapEdge(
                    supplier=edge.supplier,
                    customer=edge.customer,
                    confidence=edge.scored.confidence,
                    freshness=edge.scored.freshness,
                    reason="missing " + ",".join(missing) if missing else "schema-invalid edge",
                )
            )
        else:
            edges.append(payload)
            edge_details[f"{edge.supplier}->{edge.customer}"] = edge_detail(
                edge, _edge_claims(edge, valid_claims)
            )

    companies: list[dict[str, Any]] = []
    for t in sorted(tickers):
        meta = (company_meta or {}).get(t) or {}
        company: dict[str, Any] = {"ticker": t, "name": meta.get("name") or t}
        if meta.get("domain"):
            company["domain"] = meta["domain"]
        companies.append(company)

    source_nodes: dict[str, dict[str, Any]] = {}
    for record in sources or []:
        record = dict(record)
        source_id = record.pop("id")
        if not validate("Source", record):
            source_nodes[source_id] = record
    # Any source referenced by a claim but not supplied gets a bare reference node.
    for claim in valid_claims:
        source_nodes.setdefault(claim["source_id"], {})

    # Only keep source refs for edges that were admitted (publishable figures).
    admitted_keys = {f"{e['supplier']}->{e['customer']}" for e in edges}
    all_refs = edge_source_refs(valid_claims, source_nodes)
    edge_sources = {k: v for k, v in all_refs.items() if k in admitted_keys}

    return ThemeBuild(
        theme_id=state.theme_id,
        version=version,
        created_at=created_at or datetime.now(UTC),
        companies=companies,
        edges=edges,
        claims=valid_claims,
        sources=source_nodes,
        gap_edges=gap_edges,
        edge_sources=edge_sources,
        edge_details=edge_details,
    )
