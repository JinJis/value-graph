"""[M6-FEED-04] PostgresFeedRepository against a live database.

Gated behind VALUEGRAPH_DB_TESTS=1 (requires migrations through 0010 applied).
"""

from __future__ import annotations

import os
from datetime import datetime

import pytest

from services.engine.db.config import DbSettings
from services.engine.themes.models import ThemeCreate
from services.engine.themes.repository import PostgresThemeRepository
from services.pipeline.feed.models import FeedItemCreate
from services.pipeline.feed.repository import PostgresFeedRepository

pytestmark = pytest.mark.skipif(
    os.environ.get("VALUEGRAPH_DB_TESTS") != "1",
    reason="set VALUEGRAPH_DB_TESTS=1 (with Postgres up + migrations applied) to run",
)


def test_feed_items_persist_and_filter_by_entity() -> None:
    settings = DbSettings.from_env()
    theme = PostgresThemeRepository(settings).create_theme(ThemeCreate(name="FEED DBTEST"))
    repo = PostgresFeedRepository(settings)

    repo.add_item(
        theme.id,
        FeedItemCreate(
            title="NVIDIA earnings call",
            url="https://news/nvda",
            source_type="interview",
            published_at=datetime.fromisoformat("2026-05-01T00:00:00+00:00"),
            entities=["NVDA"],
        ),
    )
    repo.add_item(
        theme.id,
        FeedItemCreate(
            title="TSMC fab note",
            url="https://news/tsm",
            published_at=datetime.fromisoformat("2026-05-20T00:00:00+00:00"),
            entities=["TSM"],
        ),
    )

    items = repo.list_items(theme.id)
    assert [i.title for i in items] == ["TSMC fab note", "NVIDIA earnings call"]  # newest first

    nvda = repo.list_items(theme.id, entity="NVDA")
    assert len(nvda) == 1 and nvda[0].title == "NVIDIA earnings call"
