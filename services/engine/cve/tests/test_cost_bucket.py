"""Theme-aware cost-bucket classification: hint -> rules -> LLM, cached."""

from __future__ import annotations

from services.engine.cve.cost_bucket import (
    LLMCostBucketClassifier,
    RuleCostBucketClassifier,
)
from services.engine.llm.router import DEFAULT_MODELS, LLMRouter


class _Gen:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls = 0

    def generate_text(self, *, model: str, prompt: str) -> str:
        self.calls += 1
        return self.answer


def _router(gen: _Gen) -> LLMRouter:
    return LLMRouter(gen, DEFAULT_MODELS)


def test_rule_classifier_delegates_to_keyword_rules() -> None:
    rc = RuleCostBucketClassifier()
    assert rc.classify("EUV lithography equipment") == "CAPEX"
    assert rc.classify("widget") is None  # unknown -> None (ticketed downstream)


def test_llm_classifier_hint_wins_without_calling_model() -> None:
    gen = _Gen("CAPEX")
    clf = LLMCostBucketClassifier(_router(gen), theme="AI Data Centers")
    assert clf.classify("anything", hint="R&D") == "R&D"
    assert gen.calls == 0  # a valid hint short-circuits


def test_llm_classifier_uses_rules_before_the_model() -> None:
    gen = _Gen("SG&A")
    clf = LLMCostBucketClassifier(_router(gen), theme="AI Data Centers")
    assert clf.classify("fab tools") == "CAPEX"  # keyword rule
    assert gen.calls == 0  # rules answered, no LLM call


def test_llm_classifier_falls_back_to_model_for_unknown_products() -> None:
    gen = _Gen("the answer is CAPEX")
    clf = LLMCostBucketClassifier(_router(gen), theme="Wind energy")
    assert clf.classify("offshore turbine nacelle") == "CAPEX"  # rules miss -> LLM
    assert gen.calls == 1
    # Cached: a second classify of the same product does not call the model again.
    assert clf.classify("offshore turbine nacelle") == "CAPEX"
    assert gen.calls == 1


def test_llm_classifier_returns_none_when_model_unparseable() -> None:
    clf = LLMCostBucketClassifier(_router(_Gen("no idea")), theme="X")
    assert clf.classify("mystery good") is None
