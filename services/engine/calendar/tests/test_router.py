"""[M7-CAL-02] Disclosure-calendar endpoints: read coverage + upsert (manual + computed)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from services.engine.blueprint.models import Blueprint, BlueprintCompany
from services.engine.blueprint.repository import InMemoryBlueprintRepository
from services.engine.blueprint.router import get_blueprint_repository
from services.engine.calendar.repository import InMemoryCalendarRepository
from services.engine.calendar.router import get_calendar_repository
from services.engine.main import app
from services.engine.themes.models import Theme, ThemeCreate
from services.engine.themes.repository import InMemoryThemeRepository
from services.engine.themes.router import get_repository as get_theme_repository


@pytest.fixture
def ctx() -> Iterator[tuple[Theme, InMemoryCalendarRepository]]:
    themes = InMemoryThemeRepository()
    theme = themes.create_theme(ThemeCreate(name="AI Data Centers"))
    bp = InMemoryBlueprintRepository()
    bp.save(
        Blueprint(
            theme_id=theme.id,
            version=1,
            companies=[
                BlueprintCompany(ticker="INTC", name="Intel", country="US", role="supplier"),
                BlueprintCompany(ticker="HPQ", name="HP Inc.", country="US", role="customer"),
            ],
        )
    )
    cal = InMemoryCalendarRepository()
    app.dependency_overrides[get_theme_repository] = lambda: themes
    app.dependency_overrides[get_blueprint_repository] = lambda: bp
    app.dependency_overrides[get_calendar_repository] = lambda: cal
    yield theme, cal
    app.dependency_overrides.clear()


def test_calendar_lists_blueprint_companies_initially_uncovered(
    ctx: tuple[Theme, InMemoryCalendarRepository],
) -> None:
    theme, _ = ctx
    body = TestClient(app).get(f"/themes/{theme.id}/calendar").json()
    assert body["total"] == 2 and body["covered"] == 0
    assert {r["ticker"] for r in body["rows"]} == {"INTC", "HPQ"}
    assert all(r["covered"] is False for r in body["rows"])


def test_upsert_explicit_next_filing_marks_covered(
    ctx: tuple[Theme, InMemoryCalendarRepository],
) -> None:
    theme, _ = ctx
    client = TestClient(app)
    resp = client.put(
        f"/themes/{theme.id}/calendar/INTC",
        json={"next_filing_estimate": "2026-07-25", "fiscal_calendar": "quarterly"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["covered"] is True
    # Coverage now reflects the filled company.
    cov = client.get(f"/themes/{theme.id}/calendar").json()
    assert cov["covered"] == 1


def test_upsert_computes_next_filing_from_cadence(
    ctx: tuple[Theme, InMemoryCalendarRepository],
) -> None:
    theme, _ = ctx
    # No explicit estimate: last filing + quarterly cadence, anchored at a fixed `today`.
    resp = TestClient(app).put(
        f"/themes/{theme.id}/calendar/HPQ",
        json={"last_filing_date": "2026-03-01", "cadence_days": 91, "today": "2026-05-01"},
    )
    body = resp.json()
    assert resp.status_code == 200, resp.text
    assert body["next_filing_estimate"] == "2026-05-31"  # 2026-03-01 + 91d, first after today
    assert body["fiscal_calendar"] == "quarterly"  # labelled from cadence
    assert body["covered"] is True


def test_upsert_unknown_theme_404(ctx: tuple[Theme, InMemoryCalendarRepository]) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    assert (
        TestClient(app)
        .put(f"/themes/{missing}/calendar/INTC", json={"next_filing_estimate": "2026-07-25"})
        .status_code
        == 404
    )
