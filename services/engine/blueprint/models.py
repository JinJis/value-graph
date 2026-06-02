"""Blueprint models. The Pydantic models ARE the blueprint schema (validated on
every LLM round). ``BlueprintContent`` is what the DEEP model returns; the engine
wraps it with theme_id/version/provenance."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class BlueprintCompany(BaseModel):
    ticker: str
    name: str
    country: str = Field(description="ISO-2 country code, e.g. KR/US/JP/CN/TW")
    exchange: str | None = None
    role: str = Field(description="role in the chain, e.g. 'HBM supplier'")
    products: list[str] = Field(default_factory=list)
    required_data_points: list[str] = Field(
        default_factory=list,
        description="metrics needed to quantify this company's edges",
    )


class BlueprintContent(BaseModel):
    """The model's output: the candidate companies, relationship types, and notes."""

    companies: list[BlueprintCompany]
    relationship_types: list[str] = Field(default_factory=list)
    notes: str | None = None


class RoundMeta(BaseModel):
    """Log for one refinement round (delta = added + updated)."""

    round: int
    added: int
    updated: int
    delta: int
    converged: bool
    generated_by: str | None = None


class Blueprint(BlueprintContent):
    """A blueprint bound to a theme + version, with provenance."""

    theme_id: str
    version: int
    generated_by: str | None = None


class BlueprintRecord(Blueprint):
    """A persisted blueprint."""

    id: str
    created_at: datetime
    round_meta: RoundMeta | None = None


class CoverageSummary(BaseModel):
    company_count: int
    focus_countries: list[str]
    meets_threshold: bool


class BlueprintResponse(BaseModel):
    blueprint: BlueprintRecord
    coverage: CoverageSummary


class RefinementResult(BaseModel):
    rounds: list[RoundMeta]
    final: BlueprintRecord
    coverage: CoverageSummary
