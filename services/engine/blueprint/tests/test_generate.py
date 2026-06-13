"""[M1-BLU-02] Blueprint generation: JSON parse/validate, retry, and a gated live call."""

from __future__ import annotations

import os

import pytest

from services.engine.blueprint.coverage import focus_countries, meets_threshold
from services.engine.blueprint.generate import (
    BlueprintParseError,
    _extract_json,
    generate_blueprint,
    parse_blueprint_content,
)
from services.engine.blueprint.tests.fixtures import (
    FakeGenerator,
    sample_json,
    sample_theme,
)
from services.engine.llm.router import LLMRouter


def _router(*responses: str) -> LLMRouter:
    return LLMRouter.from_env(env={}, generator=FakeGenerator(*responses))


def test_extract_json_strips_fences() -> None:
    assert _extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_extract_json_from_report_with_trailing_fence() -> None:
    # Deep Research returns a long report (with stray braces/tables) then a fenced
    # JSON block; we must extract the LAST balanced object, not span the whole text.
    report = (
        "# Supply chain report\n\n"
        "Some prose with a stray brace { and a table | a | b |.\n\n"
        "Here are the results:\n\n"
        '```json\n{"companies": [{"ticker": "NVDA", "name": "NVIDIA", '
        '"country": "US", "role": "GPU"}], "relationship_types": ["SUPPLIES"]}\n```\n'
    )
    extracted = _extract_json(report)
    parsed = parse_blueprint_content(extracted)
    assert parsed.companies[0].ticker == "NVDA"


def test_parse_valid_content() -> None:
    content = parse_blueprint_content(sample_json())
    assert len(content.companies) == 32
    assert content.relationship_types == ["SUPPLIES"]


def test_parse_no_json_raises() -> None:
    with pytest.raises(BlueprintParseError):
        parse_blueprint_content("there is no json here")


def test_parse_schema_violation_raises() -> None:
    with pytest.raises(BlueprintParseError):
        parse_blueprint_content('{"companies": [{"name": "missing ticker"}]}')


def test_generate_blueprint_ok() -> None:
    blueprint = generate_blueprint(sample_theme(), [], _router(sample_json()), version=1)
    assert blueprint.theme_id == "theme-1"
    assert blueprint.version == 1
    assert blueprint.generated_by  # the resolved model id
    assert meets_threshold(blueprint)


def test_generate_retries_then_succeeds() -> None:
    blueprint = generate_blueprint(sample_theme(), [], _router("garbage", sample_json()))
    assert len(blueprint.companies) == 32


def test_generate_fails_after_retries() -> None:
    with pytest.raises(BlueprintParseError):
        generate_blueprint(sample_theme(), [], _router("nope", "still nope"))


@pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"),
    reason="no GOOGLE_API_KEY; skipping live Deep Research blueprint generation",
)
def test_live_blueprint_meets_coverage() -> None:
    blueprint = generate_blueprint(sample_theme(), [], LLMRouter.from_env())
    assert len(blueprint.companies) >= 30
    assert len(focus_countries(blueprint)) >= 4
