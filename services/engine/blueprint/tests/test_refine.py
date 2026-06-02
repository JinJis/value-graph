"""[M1-BLU-03] Iterative refinement: convergence, cross-round dedupe, round cap."""

from __future__ import annotations

import json
from typing import Any

from services.engine.blueprint.models import Blueprint, BlueprintRecord
from services.engine.blueprint.refine import refine_blueprint
from services.engine.blueprint.repository import InMemoryBlueprintRepository
from services.engine.blueprint.tests.fixtures import FakeGenerator, sample_theme
from services.engine.llm.router import LLMRouter
from services.engine.themes.models import Theme


def _router(*responses: str) -> LLMRouter:
    return LLMRouter.from_env(env={}, generator=FakeGenerator(*responses))


def _content(tickers: list[str], country: str = "US") -> dict[str, Any]:
    return {
        "companies": [
            {"ticker": t, "name": f"Name {t}", "country": country, "role": "supplier"}
            for t in tickers
        ],
        "relationship_types": ["SUPPLIES"],
        "notes": None,
    }


def _seed(repo: InMemoryBlueprintRepository, theme: Theme, tickers: list[str]) -> BlueprintRecord:
    return repo.save(Blueprint(theme_id=theme.id, version=1, **_content(tickers)))


def test_converges_when_round_adds_nothing() -> None:
    theme = sample_theme()
    repo = InMemoryBlueprintRepository()
    base = _seed(repo, theme, ["A", "B"])
    result = refine_blueprint(theme, base, _router(json.dumps(_content(["A", "B"]))), repo)
    assert len(result.rounds) == 1
    assert result.rounds[0].converged is True
    assert result.rounds[0].delta == 0
    assert result.final.version == 2


def test_dedupe_across_rounds() -> None:
    theme = sample_theme()
    repo = InMemoryBlueprintRepository()
    base = _seed(repo, theme, ["A", "B"])
    # round 2 adds C (and re-lists A); round 3 adds nothing new -> converge.
    router = _router(json.dumps(_content(["A", "C"])), json.dumps(_content(["A", "B", "C"])))
    result = refine_blueprint(theme, base, router, repo)
    tickers = [c.ticker for c in result.final.companies]
    assert sorted(tickers) == ["A", "B", "C"]
    assert tickers.count("A") == 1  # no duplicate


def test_round_cap_stops_at_three_total() -> None:
    theme = sample_theme()
    repo = InMemoryBlueprintRepository()
    base = _seed(repo, theme, ["A"])
    # every round adds a new ticker -> never converges; capped at version 3.
    router = _router(
        json.dumps(_content(["A", "B"])),
        json.dumps(_content(["A", "B", "C"])),
        json.dumps(_content(["A", "B", "C", "D"])),
    )
    result = refine_blueprint(theme, base, router, repo)
    assert [m.round for m in result.rounds] == [2, 3]
    assert result.final.version == 3
    assert result.final.round_meta is not None and result.final.round_meta.round == 3
