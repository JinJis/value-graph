"""Connector manifest — the platform keystone.

Each data source (connector) publishes a machine-readable manifest describing its
resources, their params/output, the **provenance** outputs carry, freshness/cost,
the upstream credential it needs, and its **license / redistribution policy**.

This single artifact is read by every later surface:
  * REST docs · MCP tool generation · RAG source registration · NL grounding
  * entitlements (a tenant activates a connector) · metering (cost tier)
  * governance (license policy → what may be redistributed to tenants)

P0 adds the descriptor + a catalog endpoint; it changes no endpoint behavior.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class CostTier(str, Enum):
    free = "free"  # keyless / no upstream cost
    low = "low"
    medium = "medium"
    high = "high"


class Freshness(str, Enum):
    realtime = "realtime"
    eod = "eod"  # end-of-day / delayed price
    periodic = "periodic"  # as fresh as the last filing/report
    static = "static"


class License(BaseModel):
    """Redistribution policy for a connector's data — drives platform governance."""

    id: str = Field(..., description="Policy id, e.g. 'us-public-domain', 'restricted-byo'.")
    redistribution: bool = Field(..., description="May the platform redistribute this data to tenants?")
    attribution_required: bool = False
    note: str | None = None
    terms_url: str | None = None


class Provenance(BaseModel):
    """Which provenance fields this resource's output carries (the trust envelope)."""

    source: str = Field(..., description="Human name of the upstream source, e.g. 'SEC EDGAR'.")
    as_of_field: str | None = Field(None, description="Output field giving the data's as-of date.")
    source_link_field: str | None = Field(None, description="Output field linking to the source document.")
    confidence: bool = Field(False, description="Whether outputs carry a confidence tier/interval yet.")
    freshness: Freshness = Freshness.periodic


class ResourceParam(BaseModel):
    name: str
    type: str = "string"
    required: bool = False
    description: str | None = None
    enum: list[str] | None = None


class Resource(BaseModel):
    name: str = Field(..., description="Resource id within the connector, e.g. 'income_statements'.")
    description: str
    method: str = "GET"
    path: str = Field(..., description="The REST path that serves this resource (must be a real route).")
    params: list[ResourceParam] = []
    output_model: str | None = Field(None, description="Generated response-model class name, when applicable.")
    markets: list[str] = ["US", "KR"]
    cost_tier: CostTier = CostTier.low
    provenance: Provenance


class UpstreamCredential(BaseModel):
    requires_key: bool
    key_env: str | None = None
    signup_url: str | None = None


class ConnectorManifest(BaseModel):
    id: str = Field(..., description="Stable connector id, e.g. 'sec_edgar'. Unit of activation.")
    name: str
    domain: str = Field(..., description="Primary domain, e.g. 'us-fundamentals', 'prices', 'macro'.")
    description: str
    markets: list[str]
    upstream: UpstreamCredential
    license: License
    resources: list[Resource]
