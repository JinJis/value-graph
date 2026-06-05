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
from collections.abc import Iterable

from pydantic import ValidationError

from services.engine.blueprint.models import (
    Blueprint,
    BlueprintCompany,
    BlueprintContent,
    ResearchBlueprintContent,
)
from services.engine.blueprint.prompt import build_research_generate_prompt
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
) -> Blueprint:
    """First-pass blueprint generation via the Deep Research agent.

    Streams the agent's cited report, parses the trailing JSON, and (when a
    ``theme_repo`` is given) records a Source per citation. The 2-attempt retry is a
    last-resort guard against a malformed JSON tail — Deep Research runs are slow, so
    we only re-run if the structured block can't be parsed at all."""
    prompt = build_research_generate_prompt(theme, source_hints)
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
    )
