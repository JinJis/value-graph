"""Financials store + endpoints: upsert round-trip, the CVE bucket map, and the API."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from services.engine.blueprint.models import Blueprint, BlueprintCompany
from services.engine.blueprint.repository import InMemoryBlueprintRepository
from services.engine.blueprint.router import get_blueprint_repository, get_router
from services.engine.financials.models import FinancialsUpsert, to_buckets
from services.engine.financials.repository import (
    InMemoryFinancialsRepository,
    financials_map,
    set_bucket,
)
from services.engine.financials.research import research_financials_events
from services.engine.financials.router import get_financials_repository
from services.engine.llm.router import DEFAULT_MODELS, LLMRouter
from services.engine.main import app
from services.engine.themes.models import ThemeCreate
from services.engine.themes.repository import InMemoryThemeRepository
from services.engine.themes.router import get_repository as get_theme_repository
from services.engine.themes.router import get_storage
from services.engine.tickets.models import TicketCreate
from services.engine.tickets.repository import InMemoryTicketRepository
from services.engine.tickets.router import get_ticket_repository

_FIN_PAYLOAD = json.dumps(
    {
        "financials": [
            {
                "ticker": "HPQ",
                "revenue": 53000,
                "cogs": 43000,
                "as_of": "2025-10-31",
                "source_url": "https://example.com/hpq-10k",
            }
        ]
    }
)


class _ResearchGen:
    def generate_text(self, *, model: str, prompt: str) -> str:
        return ""

    def deep_research_stream(
        self, *, agent: str, prompt: str
    ) -> Iterator[dict[str, str]]:
        yield {"kind": "text", "text": _FIN_PAYLOAD}


def _research_router() -> LLMRouter:
    return LLMRouter(_ResearchGen(), DEFAULT_MODELS)


def test_to_buckets_maps_fields_and_skips_unset() -> None:
    buckets = to_buckets(
        FinancialsUpsert(company_ticker="INTC", revenue=100.0, cogs=80.0, rnd=20.0)
    )
    assert buckets == {"revenue": 100.0, "COGS": 80.0, "R&D": 20.0}
    assert "CAPEX" not in buckets  # unset -> omitted


def test_upsert_replaces_and_map_for_builds_pipeline_input() -> None:
    repo = InMemoryFinancialsRepository()
    repo.upsert(FinancialsUpsert(company_ticker="INTC", revenue=90.0))
    repo.upsert(FinancialsUpsert(company_ticker="INTC", revenue=100.0))  # replace
    repo.upsert(FinancialsUpsert(company_ticker="HPQ", cogs=221.0))

    intc = repo.get("INTC")
    assert intc is not None and intc.revenue == 100.0
    mapped = financials_map(repo, ["INTC", "HPQ", "NVDA"])
    assert mapped == {"INTC": {"revenue": 100.0}, "HPQ": {"COGS": 221.0}}  # NVDA: no data


def test_set_bucket_preserves_other_buckets() -> None:
    repo = InMemoryFinancialsRepository()
    repo.upsert(FinancialsUpsert(company_ticker="HPQ", revenue=53000.0))
    set_bucket(repo, "HPQ", "cogs", 43000.0, source="https://x")
    rec = repo.get("HPQ")
    assert rec is not None
    assert rec.revenue == 53000.0 and rec.cogs == 43000.0  # revenue preserved
    assert set_bucket(repo, "HPQ", "bogus", 1.0) is None  # unknown field


def test_research_financials_fills_store() -> None:
    themes = InMemoryThemeRepository()
    theme = themes.create_theme(ThemeCreate(name="AI Data Centers"))
    companies = [BlueprintCompany(ticker="HPQ", name="HP Inc.", country="US", role="customer")]
    fin = InMemoryFinancialsRepository()
    events = list(research_financials_events(theme, companies, fin, _research_router()))
    kinds = [e["event"] for e in events]

    assert "prompt" in kinds and any(e["event"] == "filled" for e in events)
    assert kinds[-1] == "done"
    # A single company is one batch -> no batch framing (back-compat with the old single call).
    assert "batch_start" not in kinds
    rec = fin.get("HPQ")
    assert rec is not None and rec.revenue == 53000.0 and rec.cogs == 43000.0


_FIN_PAYLOAD_MULTI = json.dumps(
    {
        "financials": [
            {"ticker": "HPQ", "currency": "USD", "revenue": 53000, "cogs": 43000,
             "as_of": "2025-10-31", "source_url": "https://example.com/hpq"},
            {"ticker": "INTC", "currency": "USD", "revenue": 54000, "cogs": 40000,
             "as_of": "2025-12-31", "source_url": "https://example.com/intc"},
        ]
    }
)


class _MultiResearchGen:
    """Every Deep Research call returns both companies' figures; each batch's resolver keeps
    only the company that batch asked about."""

    def __init__(self) -> None:
        self.calls = 0

    def generate_text(self, *, model: str, prompt: str) -> str:
        return ""

    def deep_research_stream(self, *, agent: str, prompt: str) -> Iterator[dict[str, str]]:
        self.calls += 1
        yield {"kind": "text", "text": _FIN_PAYLOAD_MULTI}


def test_research_financials_runs_sequential_batches() -> None:
    themes = InMemoryThemeRepository()
    theme = themes.create_theme(ThemeCreate(name="AI Data Centers"))
    companies = [
        BlueprintCompany(ticker="HPQ", name="HP Inc.", country="US", role="customer"),
        BlueprintCompany(ticker="INTC", name="Intel", country="US", role="supplier"),
    ]
    fin = InMemoryFinancialsRepository()
    gen = _MultiResearchGen()
    events = list(
        research_financials_events(
            theme, companies, fin, LLMRouter(gen, DEFAULT_MODELS), batch_size=1
        )
    )

    # batch_size=1 over two companies -> two sequential Deep Research calls.
    assert gen.calls == 2
    starts = [e for e in events if e["event"] == "batch_start"]
    assert [s["index"] for s in starts] == [1, 2] and starts[0]["total"] == 2
    filled = {e["ticker"] for e in events if e["event"] == "filled"}
    assert filled == {"HPQ", "INTC"}
    assert events[-1] == {"event": "done", "filled": 2}
    assert fin.get("HPQ") and fin.get("INTC")  # both batches upserted their own company


def test_research_financials_skips_companies_already_on_file() -> None:
    """The "research ALL" action (skip_filled) leaves companies that already have revenue
    untouched — no duplicate Deep Research spend — and only researches the rest."""
    themes = InMemoryThemeRepository()
    theme = themes.create_theme(ThemeCreate(name="AI Data Centers"))
    companies = [
        BlueprintCompany(ticker="HPQ", name="HP Inc.", country="US", role="customer"),
        BlueprintCompany(ticker="INTC", name="Intel", country="US", role="supplier"),
    ]
    fin = InMemoryFinancialsRepository()
    fin.upsert(FinancialsUpsert(company_ticker="INTC", revenue=54000.0))  # already secured

    events = list(
        research_financials_events(theme, companies, fin, _research_router(), skip_filled=True)
    )
    skipped = next(e for e in events if e["event"] == "skipped")
    assert skipped["tickers"] == ["INTC"] and skipped["count"] == 1
    # The prompt only asked about the still-missing company.
    prompt = next(e for e in events if e["event"] == "prompt")["text"]
    assert "HPQ" in prompt and "INTC" not in prompt
    intc = fin.get("INTC")
    assert intc is not None and intc.revenue == 54000.0  # untouched


def test_research_financials_all_filled_short_circuits() -> None:
    """When every company already has financials, skip_filled researches nothing."""
    themes = InMemoryThemeRepository()
    theme = themes.create_theme(ThemeCreate(name="AI Data Centers"))
    companies = [BlueprintCompany(ticker="HPQ", name="HP Inc.", country="US", role="customer")]
    fin = InMemoryFinancialsRepository()
    fin.upsert(FinancialsUpsert(company_ticker="HPQ", revenue=53000.0))

    events = list(
        research_financials_events(theme, companies, fin, _research_router(), skip_filled=True)
    )
    kinds = [e["event"] for e in events]
    assert "prompt" not in kinds  # no Deep Research call
    assert not any(e["event"] == "filled" for e in events)
    assert kinds[-1] == "done"


def test_research_financials_endpoint_streams_and_fills() -> None:
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
    fin = InMemoryFinancialsRepository()
    app.dependency_overrides[get_theme_repository] = lambda: themes
    app.dependency_overrides[get_blueprint_repository] = lambda: blueprints
    app.dependency_overrides[get_financials_repository] = lambda: fin
    app.dependency_overrides[get_router] = lambda: _research_router()
    try:
        resp = TestClient(app).post(f"/themes/{theme.id}/financials/research/stream")
        assert resp.status_code == 200, resp.text
        frames = [
            json.loads(line[5:].strip())
            for line in resp.text.splitlines()
            if line.startswith("data:")
        ]
        assert any(f["event"] == "filled" for f in frames)
        assert frames[-1]["event"] == "done"
    finally:
        app.dependency_overrides.clear()
    rec = fin.get("HPQ")
    assert rec is not None and rec.revenue == 53000.0


def test_research_financials_endpoint_filters_by_tickers() -> None:
    themes = InMemoryThemeRepository()
    theme = themes.create_theme(ThemeCreate(name="AI Data Centers"))
    blueprints = InMemoryBlueprintRepository()
    blueprints.save(
        Blueprint(
            theme_id=theme.id,
            version=1,
            companies=[
                BlueprintCompany(ticker="HPQ", name="HP Inc.", country="US", role="customer"),
                BlueprintCompany(ticker="INTC", name="Intel", country="US", role="supplier"),
            ],
        )
    )
    fin = InMemoryFinancialsRepository()
    app.dependency_overrides[get_theme_repository] = lambda: themes
    app.dependency_overrides[get_blueprint_repository] = lambda: blueprints
    app.dependency_overrides[get_financials_repository] = lambda: fin
    app.dependency_overrides[get_router] = lambda: _research_router()
    try:
        client = TestClient(app)
        ok = client.post(f"/themes/{theme.id}/financials/research/stream?tickers=HPQ")
        assert ok.status_code == 200, ok.text
        prompt = next(
            json.loads(line[5:])
            for line in ok.text.splitlines()
            if line.startswith("data:") and '"event": "prompt"' in line
        )
        assert "HPQ" in prompt["text"] and "INTC" not in prompt["text"]  # only HPQ researched

        # An unknown ticker -> 404 (not a silent all-companies run).
        bad = client.post(f"/themes/{theme.id}/financials/research/stream?tickers=NVDA")
        assert bad.status_code == 404
    finally:
        app.dependency_overrides.clear()
    assert fin.get("HPQ") is not None and fin.get("INTC") is None  # only HPQ filled


def test_research_financials_endpoint_honors_batch_size() -> None:
    themes = InMemoryThemeRepository()
    theme = themes.create_theme(ThemeCreate(name="AI Data Centers"))
    blueprints = InMemoryBlueprintRepository()
    blueprints.save(
        Blueprint(
            theme_id=theme.id,
            version=1,
            companies=[
                BlueprintCompany(ticker="HPQ", name="HP Inc.", country="US", role="customer"),
                BlueprintCompany(ticker="INTC", name="Intel", country="US", role="supplier"),
            ],
        )
    )
    fin = InMemoryFinancialsRepository()
    app.dependency_overrides[get_theme_repository] = lambda: themes
    app.dependency_overrides[get_blueprint_repository] = lambda: blueprints
    app.dependency_overrides[get_financials_repository] = lambda: fin
    app.dependency_overrides[get_router] = lambda: LLMRouter(
        _MultiResearchGen(), DEFAULT_MODELS
    )
    try:
        client = TestClient(app)
        resp = client.post(
            f"/themes/{theme.id}/financials/research/stream?batch_size=1"
        )
        assert resp.status_code == 200, resp.text
        frames = [
            json.loads(line[5:].strip())
            for line in resp.text.splitlines()
            if line.startswith("data:")
        ]
        starts = [f for f in frames if f["event"] == "batch_start"]
        assert [s["index"] for s in starts] == [1, 2] and starts[0]["total"] == 2
        assert frames[-1] == {"event": "done", "filled": 2}

        # Out-of-range batch size is rejected by the query validator.
        bad = client.post(
            f"/themes/{theme.id}/financials/research/stream?batch_size=0"
        )
        assert bad.status_code == 422
    finally:
        app.dependency_overrides.clear()
    assert fin.get("HPQ") is not None and fin.get("INTC") is not None


@pytest.fixture
def client() -> Iterator[TestClient]:
    repo = InMemoryFinancialsRepository()  # one instance shared across requests
    app.dependency_overrides[get_financials_repository] = lambda: repo
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_put_then_list_financials(client: TestClient) -> None:
    put = client.put(
        "/financials/INTC", json={"company_ticker": "ignored", "revenue": 100.0}
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["company_ticker"] == "INTC"  # path wins over body
    assert body["revenue"] == 100.0

    listed = client.get("/financials?tickers=INTC,HPQ").json()
    assert len(listed) == 1 and listed[0]["company_ticker"] == "INTC"


class _NoStorage:
    def save(self, key: str, data: bytes) -> None: ...
    def load(self, key: str) -> bytes:
        return b""

    def exists(self, key: str) -> bool:
        return False


def test_accepting_financial_ticket_fills_the_store() -> None:
    themes = InMemoryThemeRepository()
    theme = themes.create_theme(ThemeCreate(name="AI Data Centers"))
    tickets = InMemoryTicketRepository()
    fin = InMemoryFinancialsRepository()
    ticket = tickets.create_open_ticket(
        theme.id, TicketCreate(target="INTC", metric="financials:revenue")
    )
    assert ticket is not None
    # Deep Research found a value for this financial ticket.
    tickets.set_research_proposal(
        ticket.id, {"value": "100", "source_url": "https://example.com/intc-10k"}
    )

    app.dependency_overrides[get_theme_repository] = lambda: themes
    app.dependency_overrides[get_ticket_repository] = lambda: tickets
    app.dependency_overrides[get_storage] = lambda: _NoStorage()
    app.dependency_overrides[get_financials_repository] = lambda: fin
    try:
        resp = TestClient(app).post(
            f"/tickets/{ticket.id}/evidence",
            data={"url": "https://example.com/intc-10k", "type": "report"},
        )
        assert resp.status_code == 201, resp.text
    finally:
        app.dependency_overrides.clear()

    # Accepting the financial ticket wrote revenue into the financials store.
    rec = fin.get("INTC")
    assert rec is not None and rec.revenue == 100.0
