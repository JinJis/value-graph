"""Blueprint generation: run the Deep Research agent, parse + validate JSON.

The first-pass generation goes through the RESEARCH tier — the Gemini Deep Research
agent — which actually searches and reads the live web, so every company comes back
with a real, retrieved citation instead of the hallucinated/dead URLs a plain
generate_content call produces. The agent returns a long cited report ending in a
fenced JSON block; we extract that block (robust to braces/tables in the prose),
validate it against the schema, and create one Source per distinct citation.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Generator, Iterable
from typing import Any

from pydantic import ValidationError

from services.engine.blueprint.models import (
    Blueprint,
    BlueprintCompany,
    BlueprintContent,
    ResearchBlueprintContent,
)
from services.engine.blueprint.prompt import (
    DEFAULT_TARGET_COMPANIES,
    build_research_generate_prompt,
)
from services.engine.llm.router import LLMRouter, Tier
from services.engine.themes.models import SourceCreate, Theme
from services.engine.themes.repository import ThemeRepository

_JSON_NUDGE = "\n\nEnd your reply with ONLY the fenced ```json block, no text after it."


class BlueprintParseError(ValueError):
    """The model output could not be parsed/validated as a blueprint."""


def _balanced_object(text: str) -> str:
    """Return the first complete ``{...}`` object in ``text`` (brace-balanced, string
    aware). Deep Research reports contain stray braces and tables, so a naive
    ``find('{')..rfind('}')`` grabs an invalid span — this walks the structure."""
    start = text.find("{")
    if start == -1:
        raise BlueprintParseError("no JSON object found in model output")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise BlueprintParseError("no complete JSON object found in model output")


_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)


def _extract_json(text: str) -> str:
    """Pull the JSON object out of model output. Prefers the LAST fenced code block
    (the agent is told to end with one), else scans the raw text for a balanced
    object — so it works for both a bare JSON reply and a long report + fence."""
    blocks = _FENCE_RE.findall(text)
    candidate = blocks[-1] if blocks else text
    return _balanced_object(candidate)


def parse_blueprint_content(text: str) -> BlueprintContent:
    try:
        return BlueprintContent.model_validate_json(_extract_json(text))
    except ValidationError as exc:
        raise BlueprintParseError(f"blueprint failed schema validation: {exc}") from exc


def parse_research_blueprint_content(text: str) -> ResearchBlueprintContent:
    try:
        return ResearchBlueprintContent.model_validate_json(_extract_json(text))
    except ValidationError as exc:
        raise BlueprintParseError(f"blueprint failed schema validation: {exc}") from exc


# When a Deep Research report doesn't contain the requested JSON, a cheap model extracts it
# from the report instead of re-running the (slow, expensive) agent. Shared by every research
# JSON consumer (blueprint/chain/financials/...) — same shape, one place.
_STRUCTURE_FRAME = (
    "You are a strict JSON formatter. From the RESEARCH REPORT below, output EXACTLY the JSON "
    "specified in the INSTRUCTIONS — extract only what the report states; do NOT invent values "
    "or URLs. Return ONLY the JSON (no prose, no fences).\n\n"
    "INSTRUCTIONS (the required JSON shape):\n{shape}\n\nRESEARCH REPORT:\n{report}"
)


def structure_report_json(
    report: str, shape: str, router: LLMRouter, *, tier: Tier = Tier.MEDIUM
) -> str:
    """Extract strict JSON from a prose research report with a cheap model; returns JSON text.

    ``shape`` is the research prompt's instruction text (it already describes the target JSON).
    Raises :class:`BlueprintParseError` if no JSON object can be found in the model's output.
    """
    prompt = _STRUCTURE_FRAME.format(shape=shape, report=report)
    return _extract_json(router.generate(tier, prompt))


def parse_with_structuring(
    buffer: str,
    parse: Callable[[str], Any],
    *,
    shape: str,
    router: LLMRouter,
    tier: Tier = Tier.MEDIUM,
) -> Generator[dict[str, Any], None, Any]:
    """Parse the JSON a research report should contain; if it's missing/invalid, extract it
    with a cheap model (emitting a ``parse: structuring`` event) INSTEAD of re-running Deep
    Research. Returns the parsed value; re-raises the parse error if structuring also fails so
    the caller's attempt loop can decide whether to retry the agent.
    """
    try:
        return parse(buffer)
    except (ValueError, ValidationError, BlueprintParseError):
        pass
    yield {
        "event": "parse",
        "status": "structuring",
        "detail": f"no JSON in the report; extracting it with {router.model_for(tier)}",
    }
    return parse(structure_report_json(buffer, shape, router, tier=tier))


def to_blueprint_company(company: BlueprintCompany) -> BlueprintCompany:
    """Coerce a research/discovery company to a plain :class:`BlueprintCompany`,
    dropping ``source_publisher`` (it lives on the Source row, not the node)."""
    return BlueprintCompany(**company.model_dump(exclude={"source_publisher"}))


def create_citation_sources(
    theme_id: str, companies: Iterable[BlueprintCompany], theme_repo: ThemeRepository
) -> int:
    """Create one Source row per distinct, non-empty citation URL. Returns the count.

    Each cited company points at a real page the agent retrieved; we de-duplicate by
    URL so a source shared by several companies is recorded once."""
    created = 0
    seen: set[str] = set()
    for company in companies:
        url = (getattr(company, "source_url", None) or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        theme_repo.add_source(
            theme_id,
            SourceCreate(
                type="report",
                url=url,
                publisher=getattr(company, "source_publisher", None),
            ),
        )
        created += 1
    return created


def generate_blueprint(
    theme: Theme,
    source_hints: list[str],
    router: LLMRouter,
    *,
    version: int = 1,
    tier: Tier = Tier.RESEARCH,
    attempts: int = 2,
    theme_repo: ThemeRepository | None = None,
    target_count: int = DEFAULT_TARGET_COMPANIES,
) -> Blueprint:
    """First-pass blueprint generation via the Deep Research agent.

    Streams the agent's cited report, parses the trailing JSON, and (when a
    ``theme_repo`` is given) records a Source per citation. The 2-attempt retry is a
    last-resort guard against a malformed JSON tail — Deep Research runs are slow, so
    we only re-run if the structured block can't be parsed at all."""
    prompt = build_research_generate_prompt(theme, source_hints, target_count=target_count)
    last_error: BlueprintParseError | None = None
    content: ResearchBlueprintContent | None = None
    for attempt in range(attempts):
        nudge = "" if attempt == 0 else _JSON_NUDGE
        buffer = "".join(
            delta["text"]
            for delta in router.deep_research_stream(tier, prompt + nudge)
            if delta.get("kind") == "text"
        )
        try:
            content = parse_research_blueprint_content(buffer)
            break
        except BlueprintParseError as exc:
            last_error = exc
    if content is None:
        raise last_error or BlueprintParseError("blueprint generation failed")

    if theme_repo is not None:
        create_citation_sources(theme.id, content.companies, theme_repo)

    return Blueprint(
        theme_id=theme.id,
        version=version,
        generated_by=router.model_for(tier),
        companies=[to_blueprint_company(c) for c in content.companies],
        relationship_types=content.relationship_types,
        notes=content.notes,
        target_count=target_count,
    )
