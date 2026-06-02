"""[M1-BLU-03] Company de-dup/merge — no two entries for the same ticker/alias."""

from __future__ import annotations

from services.engine.blueprint.dedupe import (
    dedupe_companies,
    merge_companies,
    normalize_ticker,
    union_list,
)
from services.engine.blueprint.models import BlueprintCompany


def _c(
    ticker: str,
    name: str,
    country: str = "US",
    *,
    exchange: str | None = None,
    products: list[str] | None = None,
) -> BlueprintCompany:
    return BlueprintCompany(
        ticker=ticker,
        name=name,
        country=country,
        role="supplier",
        exchange=exchange,
        products=products or [],
    )


def test_normalize_ticker() -> None:
    assert normalize_ticker(" nvda ") == "NVDA"
    assert normalize_ticker("NASDAQ:NVDA") == "NVDA"


def test_union_list_preserves_order_dedupes() -> None:
    assert union_list(["a", "b"], ["b", "c"]) == ["a", "b", "c"]


def test_dedupe_by_ticker() -> None:
    out = dedupe_companies([_c("NVDA", "NVIDIA"), _c("nvda", "Nvidia Corp")])
    assert len(out) == 1
    assert out[0].ticker == "NVDA"


def test_dedupe_by_name_alias() -> None:
    # Same normalized name + country, different ticker -> one company.
    out = dedupe_companies(
        [_c("005930.KS", "Samsung Electronics", "KR"), _c("SSNLF", "samsung electronics", "KR")]
    )
    assert len(out) == 1


def test_merge_fills_fields_and_unions_lists() -> None:
    existing = [_c("NVDA", "NVIDIA", exchange=None, products=["GPU"])]
    incoming = [_c("NVDA", "NVIDIA", exchange="NASDAQ", products=["DPU"])]
    result = merge_companies(existing, incoming)
    assert result.added == 0 and result.updated == 1
    merged = result.companies[0]
    assert merged.exchange == "NASDAQ"
    assert set(merged.products) == {"GPU", "DPU"}


def test_merge_adds_new_company() -> None:
    result = merge_companies([_c("NVDA", "NVIDIA")], [_c("TSM", "TSMC", "TW")])
    assert result.added == 1 and result.updated == 0
    assert len(result.companies) == 2


def test_merge_identical_is_zero_delta() -> None:
    base = [_c("NVDA", "NVIDIA", products=["GPU"])]
    result = merge_companies(base, [_c("NVDA", "NVIDIA", products=["GPU"])])
    assert result.added == 0 and result.updated == 0
