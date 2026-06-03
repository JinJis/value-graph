"""[M6-FEED-04] Feed ingestion (entity linking) + repository + read endpoint."""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from services.engine.feed.router import get_feed_repository
from services.engine.main import app
from services.pipeline.feed.ingest import CompanyEntity, ingest_items, link_entities
from services.pipeline.feed.models import FeedItemCreate
from services.pipeline.feed.repository import InMemoryFeedRepository

COMPANIES = [
    CompanyEntity(ticker="NVDA", name="NVIDIA"),
    CompanyEntity(ticker="TSM", name="TSMC", aliases=("Taiwan Semiconductor",)),
    CompanyEntity(ticker="INTC", name="Intel"),
]


def _item(title: str, when: str, **kw: object) -> FeedItemCreate:
    return FeedItemCreate(
        title=title,
        url="https://news/x",
        published_at=datetime.fromisoformat(when),
        **kw,  # type: ignore[arg-type]
    )


def test_entity_linking_matches_ticker_name_alias() -> None:
    assert link_entities("NVIDIA unveils new GPUs", COMPANIES) == ["NVDA"]
    assert link_entities("Taiwan Semiconductor raises capex", COMPANIES) == ["TSM"]
    assert link_entities("Intel and NVIDIA expand deal", COMPANIES) == ["INTC", "NVDA"]
    assert link_entities("A story about nobody", COMPANIES) == []


def test_ingest_links_and_persists_newest_first() -> None:
    repo = InMemoryFeedRepository()
    ingest_items(
        [
            _item("NVIDIA Q1 call", "2026-05-01T00:00:00+00:00", source_type="interview"),
            _item("TSMC fab update", "2026-05-20T00:00:00+00:00", source_type="news"),
        ],
        COMPANIES,
        repo,
        theme_id="t1",
    )
    items = repo.list_items("t1")
    assert [i.title for i in items] == ["TSMC fab update", "NVIDIA Q1 call"]  # newest first
    assert items[0].entities == ["TSM"]


def test_node_select_filters_feed_to_entity() -> None:
    repo = InMemoryFeedRepository()
    ingest_items(
        [
            _item("NVIDIA and Intel deal", "2026-05-10T00:00:00+00:00"),
            _item("TSMC news", "2026-05-11T00:00:00+00:00"),
        ],
        COMPANIES,
        repo,
        theme_id="t1",
    )
    nvda = repo.list_items("t1", entity="NVDA")
    assert len(nvda) == 1 and nvda[0].title == "NVIDIA and Intel deal"
    assert repo.list_items("t1", entity="TSM")[0].title == "TSMC news"


def test_feed_endpoint_serves_and_filters() -> None:
    repo = InMemoryFeedRepository()
    ingest_items(
        [_item("NVIDIA story", "2026-05-10T00:00:00+00:00")], COMPANIES, repo, theme_id="t1"
    )
    app.dependency_overrides[get_feed_repository] = lambda: repo
    try:
        client = TestClient(app)
        body = client.get("/themes/t1/feed").json()
        assert len(body) == 1 and body[0]["entities"] == ["NVDA"]
        # No scoring/forecast fields exist on a feed item.
        assert set(body[0]) >= {"title", "url", "source_type", "published_at", "entities"}
        assert "score" not in body[0] and "momentum" not in body[0]
        assert client.get("/themes/t1/feed?entity=TSM").json() == []
    finally:
        app.dependency_overrides.clear()
