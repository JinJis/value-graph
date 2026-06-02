"""[M1-BLU-02] Coverage acceptance bar: >=30 companies across >=4 focus countries."""

from __future__ import annotations

from services.engine.blueprint.coverage import (
    MIN_COMPANIES,
    focus_countries,
    meets_threshold,
    summarize,
)
from services.engine.blueprint.models import Blueprint, BlueprintCompany


def _company(country: str) -> BlueprintCompany:
    return BlueprintCompany(ticker="X", name="N", country=country, role="supplier")


def _blueprint(companies: list[BlueprintCompany]) -> Blueprint:
    return Blueprint(theme_id="t", version=1, companies=companies)


def test_meets_threshold_true() -> None:
    companies = [_company(["KR", "US", "JP", "CN", "TW"][i % 5]) for i in range(MIN_COMPANIES)]
    blueprint = _blueprint(companies)
    assert meets_threshold(blueprint)
    summary = summarize(blueprint)
    assert summary.meets_threshold
    assert summary.company_count == MIN_COMPANIES
    assert summary.focus_countries == ["CN", "JP", "KR", "TW", "US"]


def test_too_few_companies() -> None:
    assert not meets_threshold(_blueprint([_company("US") for _ in range(5)]))


def test_too_few_countries() -> None:
    blueprint = _blueprint([_company("US") for _ in range(MIN_COMPANIES)])
    assert not meets_threshold(blueprint)
    assert focus_countries(blueprint) == {"US"}


def test_non_focus_countries_ignored() -> None:
    companies = [_company("DE") for _ in range(MIN_COMPANIES)]  # Germany: not a focus country
    assert focus_countries(_blueprint(companies)) == set()
