"""API + internal models for themes and their sources.

``SourceType`` is reused from the canonical graph-schema (single source of truth).
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from graph_schema import SourceType


class ThemeCreate(BaseModel):
    name: str
    description: str | None = None
    seed_tickers: list[str] = Field(default_factory=list)


class Theme(BaseModel):
    id: str
    name: str
    version: int
    status: str
    description: str | None
    seed_tickers: list[str]
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SourceCreate(BaseModel):
    """Internal: everything needed to persist a Source row."""

    type: SourceType = "report"
    publisher: str | None = None
    as_of_date: date | None = None
    language: str | None = None
    url: str | None = None
    storage_key: str | None = None
    original_filename: str | None = None
    content_type: str | None = None


class SourceRecord(SourceCreate):
    """Internal: a persisted Source (includes storage_key for content retrieval)."""

    id: str
    theme_id: str
    ticket_id: str | None = None
    verification_status: str
    created_at: datetime


class SourceOut(BaseModel):
    """API response: omits the internal storage_key, adds a content URL."""

    id: str
    theme_id: str
    ticket_id: str | None
    type: SourceType
    publisher: str | None
    as_of_date: date | None
    language: str | None
    url: str | None
    verification_status: str
    original_filename: str | None
    content_type: str | None
    created_at: datetime
    content_url: str


def to_out(record: SourceRecord) -> SourceOut:
    return SourceOut(
        id=record.id,
        theme_id=record.theme_id,
        ticket_id=record.ticket_id,
        type=record.type,
        publisher=record.publisher,
        as_of_date=record.as_of_date,
        language=record.language,
        url=record.url,
        verification_status=record.verification_status,
        original_filename=record.original_filename,
        content_type=record.content_type,
        created_at=record.created_at,
        content_url=f"/sources/{record.id}/content",
    )
