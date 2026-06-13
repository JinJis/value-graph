"""Domain backfill: clean hosts, fill only blanks, resolve tickers, fail gracefully."""

from __future__ import annotations

import json

from services.engine.blueprint.domains import (
    _clean_domain,
    fill_blueprint_domains,
    research_company_domains,
)
from services.engine.blueprint.models import BlueprintCompany
from services.engine.llm.router import DEFAULT_MODELS, LLMRouter


class _Gen:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def generate_text(self, *, model: str, prompt: str) -> str:
        self.calls += 1
        return self.text


def _router(text: str) -> LLMRouter:
    return LLMRouter(_Gen(text), DEFAULT_MODELS)


def _co(ticker: str, name: str, *, domain: str | None = None) -> BlueprintCompany:
    return BlueprintCompany(
        ticker=ticker, name=name, country="US", role="x", domain=domain
    )


def test_clean_domain_normalizes_and_rejects_non_hosts() -> None:
    assert _clean_domain("https://www.NVIDIA.com/investors") == "nvidia.com"
    assert _clean_domain(" Samsung.com ") == "samsung.com"
    assert _clean_domain("not a domain") is None
    assert _clean_domain("nodot") is None
    assert _clean_domain(None) is None


def test_fill_only_blanks_and_cleans_hosts() -> None:
    companies = [
        _co("NVDA", "NVIDIA"),
        _co("AVGO", "Broadcom", domain="broadcom.com"),  # already set -> untouched
    ]
    payload = json.dumps(
        {
            "domains": [
                {"ticker": "NVDA", "domain": "https://www.nvidia.com"},
                {"ticker": "AVGO", "domain": "wrong.com"},
            ]
        }
    )
    updated, filled = fill_blueprint_domains(companies, _router(payload))
    assert filled == 1
    by = {c.ticker: c for c in updated}
    assert by["NVDA"].domain == "nvidia.com"  # scheme/www/path stripped
    assert by["AVGO"].domain == "broadcom.com"  # pre-existing domain not overwritten


def test_all_filled_short_circuits_without_calling_the_model() -> None:
    gen = _Gen("{}")
    router = LLMRouter(gen, DEFAULT_MODELS)
    companies = [_co("NVDA", "NVIDIA", domain="nvidia.com")]
    assert research_company_domains(companies, router) == {}
    assert gen.calls == 0  # nothing to research


def test_unparseable_output_yields_no_domains() -> None:
    updated, filled = fill_blueprint_domains([_co("NVDA", "NVIDIA")], _router("nope"))
    assert filled == 0
    assert updated[0].domain is None
