"""Blueprint generation: prompt the DEEP model, parse + validate JSON.

Uses the central LLM router (Gemini only). The router returns text; we instruct
JSON-only output, extract the JSON object, and validate it against the schema,
retrying once with a stricter nudge if the first attempt is unparseable.
"""

from __future__ import annotations

from pydantic import ValidationError

from services.engine.blueprint.models import Blueprint, BlueprintContent
from services.engine.blueprint.prompt import build_prompt
from services.engine.llm.router import LLMRouter, Tier
from services.engine.themes.models import Theme


class BlueprintParseError(ValueError):
    """The model output could not be parsed/validated as a blueprint."""


def _extract_json(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise BlueprintParseError("no JSON object found in model output")
    return text[start : end + 1]


def parse_blueprint_content(text: str) -> BlueprintContent:
    try:
        return BlueprintContent.model_validate_json(_extract_json(text))
    except ValidationError as exc:
        raise BlueprintParseError(f"blueprint failed schema validation: {exc}") from exc


def generate_blueprint(
    theme: Theme,
    source_hints: list[str],
    router: LLMRouter,
    *,
    version: int = 1,
    tier: Tier = Tier.DEEP,
    attempts: int = 2,
) -> Blueprint:
    prompt = build_prompt(theme, source_hints)
    last_error: BlueprintParseError | None = None
    content: BlueprintContent | None = None
    for attempt in range(attempts):
        nudge = "" if attempt == 0 else "\n\nReturn ONLY valid JSON, no prose, no fences."
        raw = router.generate(tier, prompt + nudge)
        try:
            content = parse_blueprint_content(raw)
            break
        except BlueprintParseError as exc:
            last_error = exc
    if content is None:
        raise last_error or BlueprintParseError("blueprint generation failed")

    return Blueprint(
        theme_id=theme.id,
        version=version,
        generated_by=router.model_for(tier),
        companies=content.companies,
        relationship_types=content.relationship_types,
        notes=content.notes,
    )
