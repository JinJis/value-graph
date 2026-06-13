"""Iterative blueprint refinement (PRD §8.2): re-feed the blueprint to DEEP to expand
hidden vendors, dedupe, and fill gaps — stopping at convergence or a round cap.

Each round merges the model's output into the running blueprint (de-duplicated by
ticker/alias), persists a new version with a round log, and stops when a round adds /
changes nothing (delta < threshold) or the total round count reaches the cap.
"""

from __future__ import annotations

from services.engine.blueprint.coverage import summarize
from services.engine.blueprint.dedupe import dedupe_companies, merge_companies, union_list
from services.engine.blueprint.generate import parse_blueprint_content
from services.engine.blueprint.models import (
    Blueprint,
    BlueprintRecord,
    RefinementResult,
    RoundMeta,
)
from services.engine.blueprint.prompt import build_refine_prompt
from services.engine.blueprint.repository import BlueprintRepository
from services.engine.llm.router import LLMRouter, Tier
from services.engine.themes.models import Theme

ROUND_CAP = 3
DELTA_THRESHOLD = 1


def refine_blueprint(
    theme: Theme,
    base: BlueprintRecord,
    router: LLMRouter,
    repo: BlueprintRepository,
    *,
    round_cap: int = ROUND_CAP,
    threshold: int = DELTA_THRESHOLD,
    tier: Tier = Tier.DEEP,
) -> RefinementResult:
    current: BlueprintRecord = base
    companies = dedupe_companies(base.companies)
    rounds: list[RoundMeta] = []

    while current.version < round_cap:
        raw = router.generate(tier, build_refine_prompt(theme, current))
        content = parse_blueprint_content(raw)

        merged = merge_companies(companies, content.companies)
        delta = merged.added + merged.updated
        converged = delta < threshold

        version = repo.next_version(theme.id)
        model_id = router.model_for(tier)
        meta = RoundMeta(
            round=version,
            added=merged.added,
            updated=merged.updated,
            delta=delta,
            converged=converged,
            generated_by=model_id,
        )
        new_blueprint = Blueprint(
            theme_id=theme.id,
            version=version,
            generated_by=model_id,
            companies=merged.companies,
            relationship_types=union_list(current.relationship_types, content.relationship_types),
            notes=content.notes or current.notes,
            target_count=base.target_count,
        )
        current = repo.save(new_blueprint, round_meta=meta)
        companies = merged.companies
        rounds.append(meta)
        if converged:
            break

    return RefinementResult(rounds=rounds, final=current, coverage=summarize(current))
