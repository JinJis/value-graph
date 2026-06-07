"""Financials store + endpoints: upsert round-trip, the CVE bucket map, and the API."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from services.engine.financials.models import FinancialsUpsert, to_buckets
from services.engine.financials.repository import (
    InMemoryFinancialsRepository,
    financials_map,
)
from services.engine.financials.router import get_financials_repository
from services.engine.main import app


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
