"""Blueprint coverage check — encodes the [M1-BLU-02] acceptance bar."""

from __future__ import annotations

from services.engine.blueprint.models import Blueprint, CoverageSummary

MIN_COMPANIES = 30
FOCUS_COUNTRIES = frozenset({"KR", "US", "JP", "CN", "TW"})
MIN_FOCUS_COUNTRIES = 4


def focus_countries(blueprint: Blueprint) -> set[str]:
    return {company.country.upper() for company in blueprint.companies} & FOCUS_COUNTRIES


def meets_threshold(blueprint: Blueprint) -> bool:
    return (
        len(blueprint.companies) >= MIN_COMPANIES
        and len(focus_countries(blueprint)) >= MIN_FOCUS_COUNTRIES
    )


def summarize(blueprint: Blueprint) -> CoverageSummary:
    return CoverageSummary(
        company_count=len(blueprint.companies),
        focus_countries=sorted(focus_countries(blueprint)),
        meets_threshold=meets_threshold(blueprint),
    )
