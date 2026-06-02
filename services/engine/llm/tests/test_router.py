"""[M0-LLM-04] Central Gemini router: per-tier text, env IDs, bad tier, no key in logs."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping

import pytest

from services.engine.llm.router import (
    DEFAULT_MODELS,
    ENV_VAR,
    GeminiTextGenerator,
    LLMRouter,
    Tier,
)


class FakeGenerator:
    """In-memory TextGenerator — records calls, returns deterministic text."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def generate_text(self, *, model: str, prompt: str) -> str:
        self.calls.append((model, prompt))
        return f"[{model}] echo: {prompt}"


def _router(env: Mapping[str, str] | None = None) -> tuple[LLMRouter, FakeGenerator]:
    fake = FakeGenerator()
    router = LLMRouter.from_env(env=env or {}, generator=fake)
    return router, fake


@pytest.mark.parametrize("tier", list(Tier))
def test_each_tier_returns_text(tier: Tier) -> None:
    router, fake = _router()
    out = router.generate(tier, "hello")
    assert isinstance(out, str) and out
    assert fake.calls[-1][0] == DEFAULT_MODELS[tier]


def test_model_id_read_from_env_override() -> None:
    router, fake = _router({ENV_VAR[Tier.DEEP]: "custom-deep-model"})
    router.generate(Tier.DEEP, "x")
    assert fake.calls[-1][0] == "custom-deep-model"
    # Untouched tiers fall back to the documented defaults.
    assert router.model_for(Tier.LOW) == DEFAULT_MODELS[Tier.LOW]


def test_all_models_come_from_env_when_set() -> None:
    env = {var: f"env-{tier.value}" for tier, var in ENV_VAR.items()}
    router, _ = _router(env)
    for tier in Tier:
        assert router.model_for(tier) == f"env-{tier.value}"


def test_bad_tier_raises() -> None:
    router, _ = _router()
    with pytest.raises(ValueError):
        router.generate("MEGA", "x")
    with pytest.raises(ValueError):
        router.model_for("not-a-tier")


def test_key_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    secret = "SUPER-SECRET-KEY"
    fake = FakeGenerator()
    router = LLMRouter.from_env(env={"GOOGLE_API_KEY": secret}, generator=fake)
    with caplog.at_level(logging.DEBUG):
        router.generate(Tier.MEDIUM, "prompt-text")
    blob = "\n".join(record.getMessage() for record in caplog.records)
    assert secret not in blob
    assert DEFAULT_MODELS[Tier.MEDIUM] in blob  # routing (model) IS logged


def test_generator_repr_redacts_key() -> None:
    gen = GeminiTextGenerator("SUPER-SECRET-KEY")
    assert "SUPER-SECRET-KEY" not in repr(gen)
    assert "***" in repr(gen)


def test_router_repr_redacts_key() -> None:
    gen = GeminiTextGenerator("SUPER-SECRET-KEY")
    router = LLMRouter.from_env(env={"GOOGLE_API_KEY": "SUPER-SECRET-KEY"}, generator=gen)
    assert "SUPER-SECRET-KEY" not in repr(router)


@pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"),
    reason="no GOOGLE_API_KEY set; skipping live Gemini smoke test",
)
@pytest.mark.parametrize("tier", list(Tier))
def test_live_smoke_each_tier_returns_text(tier: Tier) -> None:
    router = LLMRouter.from_env()
    out = router.generate(tier, "Reply with the single word: ok")
    assert isinstance(out, str) and out.strip()
