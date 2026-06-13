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
from services.engine.calendar.router import get_calendar_repository
from services.engine.cve.chain_research import research_chain_events
from services.engine.cve.router import get_cve_run_repository
from services.engine.cve.run_repository import InMemoryCveRunRepository
from services.engine.db.graph_store import InMemoryGraphStore
from services.engine.financials.models import FinancialsUpsert
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


class _ProseGen:
    """Deep Research returns a PROSE report (no JSON); the cheap model structures it."""

    def generate_text(self, *, model: str, prompt: str) -> str:
        if "Which company does the mention" in prompt:
            return "NONE"
        if "RESEARCH REPORT:" in prompt:  # the structuring fallback call
            return _CHAIN
        return ""

    def deep_research_stream(self, *, agent: str, prompt: str) -> Iterator[dict[str, str]]:
        yield {"kind": "thought", "text": "researching"}
        yield {"kind": "text", "text": "INTC reported 21% of revenue from HP. No JSON here."}


def _router() -> LLMRouter:
    return LLMRouter(_Gen(), DEFAULT_MODELS)


def test_chain_research_resolves_names_and_degrades_unsourced() -> None:
    """Trades survive a slightly-off ticker (resolved by name) and a missing source (kept as
    qualitative), so a real relationship still becomes a claim instead of vanishing."""
    themes = InMemoryThemeRepository()
    theme = themes.create_theme(ThemeCreate(name="AI Data Centers"))
    blueprint = _blueprint(theme.id)  # INTC (Intel), HPQ (HP Inc.)
    chain = json.dumps(
        {
            "trades": [
                {  # company NAMES instead of tickers -> resolved to INTC->HPQ
                    "supplier": "Intel",
                    "customer": "HP Inc.",
                    "relation": "supplier_revenue_share",
                    "value": 21,
                    "unit": "%",
                    "source_url": "https://example.com/intc",
                    "quote": "21% of revenue from HP",
                },
                {  # quantified but NO source -> degraded to qualitative (kept, not dropped)
                    "supplier": "INTC",
                    "customer": "HPQ",
                    "relation": "supplier_revenue_share",
                    "value": 10,
                    "unit": "%",
                    "source_url": "",
                },
                {  # genuinely unknown company -> dropped
                    "supplier": "Foobar",
                    "customer": "HPQ",
                    "relation": "qualitative",
                    "value": None,
                },
            ],
            "financials": [],
        }
    )

    class _G:
        def generate_text(self, *, model: str, prompt: str) -> str:
            return ""

        def deep_research_stream(self, *, agent: str, prompt: str) -> Iterator[dict[str, str]]:
            yield {"kind": "text", "text": chain}

    fin = InMemoryFinancialsRepository()
    events, claims = _drain(
        research_chain_events(
            theme, blueprint, themes, fin, LLMRouter(_G(), DEFAULT_MODELS), today=TODAY
        )
    )
    researched = next(e for e in events if e["event"] == "researched")
    assert researched["trades_found"] == 3
    assert researched["dropped_unknown_ticker"] == 1
    assert researched["degraded_no_source"] == 1

    assert isinstance(claims, list) and len(claims) == 2  # name-resolved + degraded
    assert {(c.subject, c.object) for c in claims} == {("INTC", "HPQ")}  # name -> ticker
    values = sorted((c.value for c in claims), key=lambda v: (v is None, v))
    assert values == [21.0, None]  # the sourced one keeps its value; the unsourced is degraded


def test_chain_research_handles_numeric_tickers() -> None:
    """Tokyo/Seoul-style numeric tickers arriving as JSON numbers don't crash parsing and
    still resolve (the whole batch used to fail on a `str` field before coercion)."""
    themes = InMemoryThemeRepository()
    theme = themes.create_theme(ThemeCreate(name="Chips"))
    blueprint = InMemoryBlueprintRepository().save(
        Blueprint(
            theme_id=theme.id,
            version=1,
            companies=[
                BlueprintCompany(ticker="6857", name="Advantest", country="JP", role="ATE"),
                BlueprintCompany(ticker="6758", name="Sony", country="JP", role="customer"),
            ],
        )
    )
    chain = json.dumps(
        {
            "trades": [
                {
                    "supplier": 6857,  # JSON number, not a string
                    "customer": 6758,
                    "relation": "supplier_revenue_share",
                    "value": 15,
                    "unit": "%",
                    "source_url": "https://example.com/x",
                    "quote": "15% of revenue",
                }
            ],
            "financials": [{"ticker": 6857, "revenue": 2400000, "source_url": "https://x"}],
        }
    )

    class _G:
        def generate_text(self, *, model: str, prompt: str) -> str:
            return ""

        def deep_research_stream(self, *, agent: str, prompt: str) -> Iterator[dict[str, str]]:
            yield {"kind": "text", "text": chain}

    fin = InMemoryFinancialsRepository()
    events, claims = _drain(
        research_chain_events(
            theme, blueprint, themes, fin, LLMRouter(_G(), DEFAULT_MODELS), today=TODAY
        )
    )
    researched = next(e for e in events if e["event"] == "researched")
    assert researched["trades_found"] == 1
    assert isinstance(claims, list) and len(claims) == 1
    # JP companies canonicalize to SYMBOL.T; the numeric trade resolves to them.
    assert {(c.subject, c.object) for c in claims} == {("6857.T", "6758.T")}
    assert fin.get("6857.T") is not None  # numeric financials ticker coerced + canonical


def test_chain_research_structures_report_without_json() -> None:
    themes = InMemoryThemeRepository()
    theme = themes.create_theme(ThemeCreate(name="AI Data Centers"))
    blueprint = _blueprint(theme.id)
    fin = InMemoryFinancialsRepository()
    events, claims = _drain(
        research_chain_events(
            theme, blueprint, themes, fin, LLMRouter(_ProseGen(), DEFAULT_MODELS), today=TODAY
        )
    )
    statuses = [e["status"] for e in events if e["event"] == "parse"]
    assert "structuring" in statuses and statuses[-1] == "ok"  # no Deep Research re-run
    assert isinstance(claims, list) and len(claims) == 1  # extracted via the cheap model


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


def test_research_chain_skips_financials_already_on_file() -> None:
    """B: a company with revenue on file is dropped from the financials ask (no dup
    Deep Research spend), while trades still cover every company."""
    themes = InMemoryThemeRepository()
    theme = themes.create_theme(ThemeCreate(name="AI Data Centers"))
    blueprint = _blueprint(theme.id)
    fin = InMemoryFinancialsRepository()
    fin.upsert(FinancialsUpsert(company_ticker="INTC", revenue=100.0))  # already filled

    events, _ = _drain(
        research_chain_events(theme, blueprint, themes, fin, _router(), today=TODAY)
    )
    reuse = next(e for e in events if e["event"] == "research")
    assert reuse["action"] == "Financials on file"
    assert reuse["detail"] == "reusing 1, researching 1"

    prompt = str(next(e for e in events if e["event"] == "prompt")["text"])
    needed = next(
        line for line in prompt.splitlines() if line.startswith("FINANCIALS NEEDED")
    )
    assert "HPQ" in needed and "INTC" not in needed  # only the missing one
    assert "KNOWN COMPANIES" in prompt and "INTC" in prompt  # trades still cover INTC


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


def test_missing_financials_lists_companies_lacking_required_buckets() -> None:
    from services.engine.cve.run_service import _missing_financials

    blueprint = _blueprint("t1")  # INTC, HPQ
    fin = InMemoryFinancialsRepository()
    fin.upsert(FinancialsUpsert(company_ticker="INTC", revenue=100.0, cogs=80.0))  # complete
    fin.upsert(FinancialsUpsert(company_ticker="HPQ", revenue=53.0))  # missing cogs
    missing = _missing_financials(blueprint, fin)
    assert missing == [{"ticker": "HPQ", "name": "HP Inc.", "missing": ["cogs"]}]


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
    # Missing financials are surfaced as guidance to the Financials step, NOT as tickets.
    assert "financials_missing" in kinds and "financial_tickets" not in kinds
    persisted = next(e for e in events if e["event"] == "persisted")
    assert int(persisted["publishable_edges"]) >= 1  # type: ignore[call-overload]
    assert int(persisted["estimated_edges"]) == 0  # type: ignore[call-overload]

    preview = client.get(f"/themes/{theme.id}/publish/preview?threshold=0.1")
    assert preview.status_code == 200 and preview.json()["can_publish"] is True
