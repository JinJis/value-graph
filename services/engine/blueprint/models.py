"""Blueprint models. The Pydantic models ARE the blueprint schema (validated on
every LLM round). ``BlueprintContent`` is what the DEEP model returns; the engine
wraps it with theme_id/version/provenance."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.engine.blueprint.identity import canonical_ticker

# Tickers differ wildly by market — alphabetic (AAPL), numeric (6857 in Tokyo, 005930 in
# Seoul), with or without an exchange suffix. An LLM may emit a numeric ticker as a JSON
# number, which would otherwise fail a `str` field and drop the whole record. Coerce numbers
# to strings so e.g. 6857 parses as "6857", then canonicalize the identity (see below).
_LLM_MODEL_CONFIG = ConfigDict(coerce_numbers_to_str=True)


class BlueprintCompany(BaseModel):
    model_config = _LLM_MODEL_CONFIG
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
    source_url: str | None = Field(
        default=None, description="provenance URL (set for companies found by discovery)"
    )

    @model_validator(mode="after")
    def _canonicalize_ticker(self) -> BlueprintCompany:
        # Canonical identity = SYMBOL[.SUFFIX] from country/exchange (e.g. 6857 -> 6857.T).
        self.ticker = canonical_ticker(
            self.ticker, country=self.country, exchange=self.exchange
        )
        return self


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
    # The admin-chosen target size at generation; drives the coverage bar. None = default.
    target_count: int | None = None


class BlueprintRecord(Blueprint):
    """A persisted blueprint."""

    id: str
    created_at: datetime
    round_meta: RoundMeta | None = None


class CoverageSummary(BaseModel):
    company_count: int
    focus_countries: list[str]
    meets_threshold: bool
    target: int  # the company-count bar this was judged against


class BlueprintResponse(BaseModel):
    blueprint: BlueprintRecord
    coverage: CoverageSummary


class RefinementResult(BaseModel):
    rounds: list[RoundMeta]
    final: BlueprintRecord
    coverage: CoverageSummary


class ResearchCompany(BlueprintCompany):
    """A company surfaced by the research-grounded initial generation.

    Like a discovered company it may carry a citation (``source_url`` +
    ``source_publisher``), but the field stays OPTIONAL here: the first pass draws
    the whole chain, and a company we couldn't yet cite is kept (drawn as a gap)
    rather than dropped — the citation is filled later by research/CVE."""

    source_publisher: str | None = None


class ResearchBlueprintContent(BaseModel):
    """The research-grounded generation output: cited companies + structure."""

    companies: list[ResearchCompany]
    relationship_types: list[str] = Field(default_factory=list)
    notes: str | None = None


class DiscoveredCompany(BlueprintCompany):
    """A constituent found by the RESEARCH discovery pass — must carry a source."""

    source_url: str  # required: each discovered company carries a Source
    source_publisher: str | None = None


class DiscoveryContent(BaseModel):
    """The RESEARCH model's output."""

    companies: list[DiscoveredCompany]


class DiscoveryResult(BaseModel):
    discovered: int
    added: int
    updated: int
    sources_created: int
    final: BlueprintRecord
    coverage: CoverageSummary
