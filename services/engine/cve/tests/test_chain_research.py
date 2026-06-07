"""Chain research: Deep Research -> Claims + financials + Sources, seeded into a build."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from services.engine.blueprint.models import Blueprint, BlueprintCompany, BlueprintRecord
from services.engine.blueprint.repository import InMemoryBlueprintRepository
from services.engine.blueprint.router import get_blueprint_repository, get_router
from services.engine.calendar.models import CalendarUpsert
from services.engine.calendar.repository import InMemoryCalendarRepository
from services.engine.cve.chain_research import research_chain_events
from services.engine.cve.router import get_calendar_repository, get_cve_run_repository
from services.engine.cve.run_repository import InMemoryCveRunRepository
from services.engine.db.graph_store import InMemoryGraphStore
from services.engine.financials.repository import InMemoryFinancialsRepository
from services.engine.financials.router import get_financials_repository
from services.engine.llm.router import DEFAULT_MODELS, LLMRouter
from services.engine.main import app
from services.engine.publish.router import get_graph_store
from services.engine.themes.models import Theme, ThemeCreate
from services.engine.themes.repository import InMemoryThemeRepository
from services.engine.themes.router import get_repository as get_theme_repository
from services.engine.themes.router import get_storage
from services.engine.tickets.repository import InMemoryTicketRepository
from services.engine.tickets.router import get_ticket_repository

TODAY = "2026-06-01"

_CHAIN = json.dumps(
    {
        "trades": [
            {
                "supplier": "INTC",
                "customer": "HPQ",
                "relation": "supplier_revenue_share",
                "value": 21,
                "unit": "%",
                "cost_bucket": "COGS",
                "as_of": "2026-05-20",
                "source_url": "https://example.com/intc-10k",
                "quote": "21% of revenue from HP",
            }
        ],
        "financials": [
            {"ticker": "INTC", "revenue": 100, "source_url": "https://example.com/intc-10k"},
            {"ticker": "HPQ", "cogs": 221, "source_url": "https://example.com/hpq-10k"},
        ],
    }
)


class _Gen:
    """Deep Research returns the canned chain JSON; generate_text covers S2 adjudication."""

    def generate_text(self, *, model: str, prompt: str) -> str:
        if "Which company does the mention" in prompt:
            return "NONE"
        return ""

    def deep_research_stream(self, *, agent: str, prompt: str) -> Iterator[dict[str, str]]:
        yield {"kind": "thought", "text": "researching the chain"}
        for i in range(0, len(_CHAIN), 50):
            yield {"kind": "text", "text": _CHAIN[i : i + 50]}


def _router() -> LLMRouter:
    return LLMRouter(_Gen(), DEFAULT_MODELS)


def _blueprint(theme_id: str) -> BlueprintRecord:
    repo = InMemoryBlueprintRepository()
    return repo.save(
        Blueprint(
            theme_id=theme_id,
            version=1,
            companies=[
                BlueprintCompany(ticker="INTC", name="Intel", country="US", role="supplier"),
                BlueprintCompany(ticker="HPQ", name="HP Inc.", country="US", role="customer"),
            ],
        )
    )


def _drain(gen: Iterator[dict[str, object]]) -> tuple[list[dict[str, object]], object]:
    events: list[dict[str, object]] = []
    try:
        while True:
            events.append(next(gen))
    except StopIteration as stop:
        return events, stop.value


def test_research_chain_persists_claims_financials_sources() -> None:
    themes = InMemoryThemeRepository()
    theme = themes.create_theme(ThemeCreate(name="AI Data Centers"))
    blueprint = _blueprint(theme.id)
    fin = InMemoryFinancialsRepository()

    events, claims = _drain(
        research_chain_events(theme, blueprint, themes, fin, _router(), today=TODAY)
    )
    kinds = [e["event"] for e in events]
    assert "prompt" in kinds and "chunk" in kinds
    researched = next(e for e in events if e["event"] == "researched")
    assert researched["trades"] == 1 and researched["financials"] == 2

    assert isinstance(claims, list) and len(claims) == 1
    assert claims[0].subject == "INTC" and claims[0].object == "HPQ"
    assert claims[0].source_id  # a Source was created and linked
    # Financials persisted (merged), and Sources created for the citations.
    intc = fin.get("INTC")
    assert intc is not None and intc.revenue == 100.0
    assert fin.get("HPQ").cogs == 221.0  # type: ignore[union-attr]
    assert len(themes.list_sources(theme.id)) == 2


def _seed_app() -> Theme:
    themes = InMemoryThemeRepository()
    theme = themes.create_theme(ThemeCreate(name="AI Data Centers"))
    blueprints = InMemoryBlueprintRepository()
    blueprints.save(
        Blueprint(
            theme_id=theme.id,
            version=1,
            companies=[
                BlueprintCompany(ticker="INTC", name="Intel", country="US", role="supplier"),
                BlueprintCompany(ticker="HPQ", name="HP Inc.", country="US", role="customer"),
            ],
        )
    )
    calendar = InMemoryCalendarRepository()
    calendar.upsert(CalendarUpsert(company_ticker="INTC", next_filing_estimate="2026-08-15"))  # type: ignore[arg-type]
    graph = InMemoryGraphStore()
    app.dependency_overrides[get_theme_repository] = lambda: themes
    app.dependency_overrides[get_blueprint_repository] = lambda: blueprints
    app.dependency_overrides[get_ticket_repository] = lambda: InMemoryTicketRepository()
    app.dependency_overrides[get_router] = lambda: _router()
    app.dependency_overrides[get_storage] = lambda: None  # no documents ingested
    app.dependency_overrides[get_graph_store] = lambda: graph
    app.dependency_overrides[get_cve_run_repository] = lambda: InMemoryCveRunRepository()
    app.dependency_overrides[get_calendar_repository] = lambda: calendar
    app.dependency_overrides[get_financials_repository] = lambda: InMemoryFinancialsRepository()
    return theme


@pytest.fixture(autouse=True)
def _clear() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _frames(text: str) -> list[dict[str, object]]:
    return [
        json.loads(line[5:].strip())
        for line in text.splitlines()
        if line.startswith("data:")
    ]


def test_research_and_build_endpoint_yields_derived_publishable_graph() -> None:
    theme = _seed_app()
    client = TestClient(app)
    resp = client.post(f"/themes/{theme.id}/cve/research/stream")
    assert resp.status_code == 200, resp.text
    events = _frames(resp.text)
    kinds = [e["event"] for e in events]

    assert "researched" in kinds
    assert kinds.count("stage") == 7  # the build phase ran S1-S7
    assert kinds[-1] == "done"
    persisted = next(e for e in events if e["event"] == "persisted")
    assert int(persisted["publishable_edges"]) >= 1  # type: ignore[call-overload]
    assert int(persisted["estimated_edges"]) == 0  # type: ignore[call-overload]

    preview = client.get(f"/themes/{theme.id}/publish/preview?threshold=0.1")
    assert preview.status_code == 200 and preview.json()["can_publish"] is True
