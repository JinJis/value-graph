"""[M3/M4] CVE run endpoint — ingests theme sources, persists a publishable build."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient

from services.engine.blueprint.models import Blueprint, BlueprintCompany
from services.engine.blueprint.repository import InMemoryBlueprintRepository
from services.engine.blueprint.router import get_blueprint_repository, get_router
from services.engine.calendar.models import CalendarUpsert
from services.engine.calendar.repository import InMemoryCalendarRepository
from services.engine.cve.router import get_calendar_repository, get_cve_run_repository
from services.engine.cve.run_repository import InMemoryCveRunRepository
from services.engine.db.graph_store import InMemoryGraphStore
from services.engine.llm.router import LLMRouter
from services.engine.main import app
from services.engine.publish.router import get_graph_store
from services.engine.themes.models import SourceCreate, Theme, ThemeCreate
from services.engine.themes.repository import InMemoryThemeRepository
from services.engine.themes.router import get_repository as get_theme_repository
from services.engine.themes.router import get_storage
from services.engine.tickets.repository import InMemoryTicketRepository
from services.engine.tickets.router import get_ticket_repository

DOC = "Intel reported that 21% of its revenue came from HP Inc. in fiscal 2026."


class _Gen:
    """Content-aware fake generator: extracts the disclosed claim, estimates the edge."""

    def generate_text(self, *, model: str, prompt: str) -> str:
        if "METRIC TO ESTIMATE" in prompt:  # S5 VSCA-est (no financials -> estimated)
            return json.dumps(
                {"value": 8, "low": 4, "high": 12, "method": "peer", "rationale": "analogy"}
            )
        if "Which company does the mention" in prompt:  # S2 adjudication (unused here)
            return "NONE"
        if "21%" in prompt:  # S1 extract
            return json.dumps(
                {
                    "claims": [
                        {
                            "relation": "supplier_revenue_share",
                            "subject": "Intel",
                            "object": "HP Inc.",
                            "value": 21,
                            "unit": "%",
                            "cost_bucket": "COGS",
                            "text_span": "21% of its revenue came from HP Inc.",
                        }
                    ]
                }
            )
        return ""


class _Storage:
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self._blobs = blobs

    def save(self, key: str, data: bytes) -> None:
        self._blobs[key] = data

    def load(self, key: str) -> bytes:
        return self._blobs[key]

    def exists(self, key: str) -> bool:
        return key in self._blobs


def _seed(*, with_blueprint: bool = True, with_source: bool = True) -> Theme:
    themes = InMemoryThemeRepository()
    theme = themes.create_theme(ThemeCreate(name="AI Data Centers"))
    if with_source:
        themes.add_source(
            theme.id,
            SourceCreate(type="filing", storage_key="k1", as_of_date=date(2026, 5, 20)),
        )
    blueprints = InMemoryBlueprintRepository()
    if with_blueprint:
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
    calendar.upsert(
        CalendarUpsert(company_ticker="INTC", next_filing_estimate=date(2026, 8, 15))
    )

    graph = InMemoryGraphStore()  # one instance: the build must persist across requests
    app.dependency_overrides[get_theme_repository] = lambda: themes
    app.dependency_overrides[get_blueprint_repository] = lambda: blueprints
    app.dependency_overrides[get_ticket_repository] = lambda: InMemoryTicketRepository()
    app.dependency_overrides[get_router] = lambda: LLMRouter.from_env(env={}, generator=_Gen())
    app.dependency_overrides[get_storage] = lambda: _Storage({"k1": DOC.encode()})
    app.dependency_overrides[get_graph_store] = lambda: graph
    app.dependency_overrides[get_cve_run_repository] = lambda: InMemoryCveRunRepository()
    app.dependency_overrides[get_calendar_repository] = lambda: calendar
    return theme


@pytest.fixture(autouse=True)
def _clear() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def test_cve_run_builds_publishable_edge() -> None:
    theme = _seed()
    client = TestClient(app)
    resp = client.post(f"/themes/{theme.id}/cve/run")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["build_version"] == 1
    assert body["documents_ingested"] == 1
    assert body["claims"] >= 1
    assert body["edges"] >= 1
    assert body["publishable_edges"] >= 1  # estimated edge, provenanced via the calendar

    # The build is now publishable through the publish preview (same graph store).
    preview = client.get(f"/themes/{theme.id}/publish/preview?threshold=0.1")
    assert preview.status_code == 200, preview.text
    assert preview.json()["can_publish"] is True


def test_cve_run_requires_blueprint() -> None:
    theme = _seed(with_blueprint=False)
    client = TestClient(app)
    assert client.post(f"/themes/{theme.id}/cve/run").status_code == 409


def test_cve_run_missing_theme_404() -> None:
    _seed()
    client = TestClient(app)
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.post(f"/themes/{missing}/cve/run").status_code == 404
