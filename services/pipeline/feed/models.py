"""[M6-FEED-04] Live Context Feed item models.

A feed item is a RAW context artifact (news / interview / filing), entity-linked to
the companies it mentions. Context only — there is NO score, momentum, or forecast
anywhere on a feed item (PRD §9.4 / CLAUDE.md scope).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

FeedSourceType = Literal["news", "interview", "filing"]


class FeedItemCreate(BaseModel):
    title: str
    url: str
    source_type: FeedSourceType = "news"
    publisher: str | None = None
    published_at: datetime
    snippet: str | None = None  # a raw excerpt, never a generated judgement
    entities: list[str] = Field(default_factory=list)  # linked tickers


class FeedItem(BaseModel):
    id: str
    theme_id: str
    title: str
    url: str
    source_type: FeedSourceType
    publisher: str | None
    published_at: datetime
    snippet: str | None
    entities: list[str]
    created_at: datetime
