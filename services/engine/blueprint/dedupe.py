"""Company de-duplication + merge (pure). No two entries for the same ticker/alias.

A company is identified by its normalized ticker; an entry with the same normalized
(name, country) but a different ticker is treated as an alias of the same company.
Merging fills missing fields and unions list fields.
"""

from __future__ import annotations

from typing import NamedTuple

from services.engine.blueprint.models import BlueprintCompany


def normalize_ticker(ticker: str) -> str:
    t = ticker.strip().upper()
    if ":" in t:  # "NASDAQ:NVDA" / "KRX:005930" -> bare symbol
        t = t.split(":")[-1].strip()
    return t


def normalize_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _name_key(company: BlueprintCompany) -> tuple[str, str]:
    return (normalize_name(company.name), company.country.strip().upper())


def union_list(a: list[str], b: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in [*a, *b]:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _merge_one(
    existing: BlueprintCompany, incoming: BlueprintCompany
) -> tuple[BlueprintCompany, bool]:
    merged = BlueprintCompany(
        ticker=existing.ticker,
        name=existing.name or incoming.name,
        country=existing.country or incoming.country,
        exchange=existing.exchange or incoming.exchange,
        role=existing.role or incoming.role,
        products=union_list(existing.products, incoming.products),
        required_data_points=union_list(
            existing.required_data_points, incoming.required_data_points
        ),
        source_url=existing.source_url or incoming.source_url,
    )
    return merged, merged != existing


class MergeResult(NamedTuple):
    companies: list[BlueprintCompany]
    added: int
    updated: int


def merge_companies(
    existing: list[BlueprintCompany], incoming: list[BlueprintCompany]
) -> MergeResult:
    result = list(existing)
    by_ticker = {normalize_ticker(c.ticker): i for i, c in enumerate(result)}
    by_name = {_name_key(c): i for i, c in enumerate(result)}
    added = 0
    updated = 0
    for company in incoming:
        tkey = normalize_ticker(company.ticker)
        nkey = _name_key(company)
        idx = by_ticker.get(tkey)
        if idx is None:
            idx = by_name.get(nkey)
        if idx is None:
            result.append(company)
            new_idx = len(result) - 1
            by_ticker[tkey] = new_idx
            by_name[nkey] = new_idx
            added += 1
        else:
            merged, changed = _merge_one(result[idx], company)
            result[idx] = merged
            if changed:
                updated += 1
    return MergeResult(companies=result, added=added, updated=updated)


def dedupe_companies(companies: list[BlueprintCompany]) -> list[BlueprintCompany]:
    return merge_companies([], companies).companies
