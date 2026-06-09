"""[M7-CAL-03] Deep Research filing history -> infer cadence -> next_filing_estimate."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date

from fastapi.testclient import TestClient

from services.engine.blueprint.models import Blueprint, BlueprintCompany
from services.engine.blueprint.repository import InMemoryBlueprintRepository
from services.engine.blueprint.router import get_blueprint_repository, get_router
from services.engine.calendar.repository import InMemoryCalendarRepository
from services.engine.calendar.research import research_calendar_events
from services.engine.calendar.router import get_calendar_repository
from services.engine.llm.router import DEFAULT_MODELS, LLMRouter
from services.engine.main import app
from services.engine.themes.models import ThemeCreate
from services.engine.themes.repository import InMemoryThemeRepository
from services.engine.themes.router import get_repository as get_theme_repository

# Four quarterly filings ~91 days apart -> cadence quarterly, next filing projected forward.
_PAYLOAD = json.dumps(
    {
        "schedules": [
            {
                "ticker": "HPQ",
                "filing_dates": ["2025-09-30", "2025-06-30", "2025-03-31", "2024-12-31"],
                "fiscal_calendar": "quarterly",
                "source_url": "https://example.com/hpq-ir",
            }
        ]
    }
)


class _ResearchGen:
    def generate_text(self, *, model: str, prompt: str) -> str:
        return ""

    def deep_research_stream(self, *, agent: str, prompt: str) -> Iterator[dict[str, str]]:
        yield {"kind": "text", "text": _PAYLOAD}


def _router() -> LLMRouter:
    return LLMRouter(_ResearchGen(), DEFAULT_MODELS)


def test_research_infers_cadence_and_next_filing() -> None:
    themes = InMemoryThemeRepository()
    theme = themes.create_theme(ThemeCreate(name="AI Data Centers"))
    companies = [BlueprintCompany(ticker="HPQ", name="HP Inc.", country="US", role="customer")]
    cal = InMemoryCalendarRepository()

    events = list(
        research_calendar_events(theme, companies, cal, _router(), today=date(2026, 1, 15))
    )
    kinds = [e["event"] for e in events]
    assert "prompt" in kinds and kinds[-1] == "done"

    filled = next(e for e in events if e["event"] == "filled")
    assert filled["ticker"] == "HPQ"
    assert filled["cadence_days"] == 91  # median quarterly gap
    assert filled["next_filing_estimate"] == "2026-03-31"  # first filing after the anchor

    entry = cal.get("HPQ")
    assert entry is not None and entry.next_filing_estimate == date(2026, 3, 31)
    assert entry.source == "https://example.com/hpq-ir"


def test_research_skips_company_without_parseable_dates() -> None:
    themes = InMemoryThemeRepository()
    theme = themes.create_theme(ThemeCreate(name="AI Data Centers"))
    companies = [BlueprintCompany(ticker="HPQ", name="HP Inc.", country="US", role="customer")]
    cal = InMemoryCalendarRepository()

    class _NoDates:
        def generate_text(self, *, model: str, prompt: str) -> str:
            return ""

        def deep_research_stream(self, *, agent: str, prompt: str) -> Iterator[dict[str, str]]:
            yield {
                "kind": "text",
                "text": json.dumps(
                    {"schedules": [{"ticker": "HPQ", "filing_dates": [], "source_url": "x"}]}
                ),
            }

    events = list(
        research_calendar_events(
            theme, companies, cal, LLMRouter(_NoDates(), DEFAULT_MODELS), today=date(2026, 1, 15)
        )
    )
    assert any(e["event"] == "skipped" for e in events)
    assert cal.get("HPQ") is None  # nothing guessed without a dated filing


def test_research_endpoint_streams_and_fills() -> None:
    themes = InMemoryThemeRepository()
    theme = themes.create_theme(ThemeCreate(name="AI Data Centers"))
    blueprints = InMemoryBlueprintRepository()
    blueprints.save(
        Blueprint(
            theme_id=theme.id,
            version=1,
            companies=[
                BlueprintCompany(ticker="HPQ", name="HP Inc.", country="US", role="customer")
            ],
        )
    )
    cal = InMemoryCalendarRepository()
    app.dependency_overrides[get_theme_repository] = lambda: themes
    app.dependency_overrides[get_blueprint_repository] = lambda: blueprints
    app.dependency_overrides[get_calendar_repository] = lambda: cal
    app.dependency_overrides[get_router] = lambda: _router()
    try:
        resp = TestClient(app).post(f"/themes/{theme.id}/calendar/research/stream")
        assert resp.status_code == 200, resp.text
        frames = [
            json.loads(line[5:].strip())
            for line in resp.text.splitlines()
            if line.startswith("data:")
        ]
        assert any(f["event"] == "filled" for f in frames)
        assert frames[-1]["event"] == "done"
        assert cal.get("HPQ") is not None  # persisted via the endpoint
    finally:
        app.dependency_overrides.clear()
