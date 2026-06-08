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


def _blueprint(
    companies: list[BlueprintCompany], *, target_count: int | None = None
) -> Blueprint:
    return Blueprint(
        theme_id="t", version=1, companies=companies, target_count=target_count
    )


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


def test_target_count_lowers_the_bar() -> None:
    # 12 companies across 4 focus countries: below the default 30, but meets a target of 12.
    companies = [_company(["KR", "US", "JP", "CN"][i % 4]) for i in range(12)]
    assert not meets_threshold(_blueprint(companies))  # default 30 bar
    judged = _blueprint(companies, target_count=12)
    assert meets_threshold(judged)
    assert summarize(judged).target == 12


def test_target_count_raises_the_bar() -> None:
    companies = [_company(["KR", "US", "JP", "CN", "TW"][i % 5]) for i in range(30)]
    assert not meets_threshold(_blueprint(companies, target_count=50))  # asked for more
    assert summarize(_blueprint(companies, target_count=50)).target == 50
