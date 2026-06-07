"""Per-company financials models — the complementary side of the CVE math.

``revenue`` + the cost buckets (COGS/CAPEX/R&D/SG&A) convert a supplier-side revenue
share into the customer-side cost share so a single disclosure can be cross-checked.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class FinancialsUpsert(BaseModel):
    company_ticker: str
    revenue: float | None = None
    cogs: float | None = None
    capex: float | None = None
    rnd: float | None = None
    sga: float | None = None
    currency: str | None = None
    as_of_date: date | None = None
    source: str | None = None


class FinancialsRecord(FinancialsUpsert):
    id: str
    updated_at: datetime


# Model field -> the CVE cost-bucket key the pipeline reads (CLAUDE.md §4 buckets).
_BUCKET_FIELDS: tuple[tuple[str, str], ...] = (
    ("revenue", "revenue"),
    ("cogs", "COGS"),
    ("capex", "CAPEX"),
    ("rnd", "R&D"),
    ("sga", "SG&A"),
)


def to_buckets(record: FinancialsUpsert) -> dict[str, float]:
    """Map a record to the ``{bucket: value}`` shape the CVE pipeline consumes (skips
    unset fields)."""
    out: dict[str, float] = {}
    for field, bucket in _BUCKET_FIELDS:
        value = getattr(record, field)
        if value is not None:
            out[bucket] = float(value)
    return out
