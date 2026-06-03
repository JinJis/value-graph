"""[M6-FEED-04] Read-only Live Context Feed endpoint (raw items; node-select filter)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from services.engine.db.config import DbSettings
from services.pipeline.feed.models import FeedItem
from services.pipeline.feed.repository import FeedRepository, PostgresFeedRepository

router = APIRouter(tags=["feed"])


def get_feed_repository() -> FeedRepository:
    return PostgresFeedRepository(DbSettings.from_env())


FeedRepoDep = Annotated[FeedRepository, Depends(get_feed_repository)]


@router.get("/themes/{theme_id}/feed", response_model=list[FeedItem])
def theme_feed(
    theme_id: str,
    repo: FeedRepoDep,
    entity: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[FeedItem]:
    """Newest-first context items for a theme; ``entity`` filters to one ticker.

    Raw context only — no score, momentum, or forecast is computed or returned.
    """
    return repo.list_items(theme_id, entity=entity, limit=limit)
