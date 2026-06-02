"""RESEARCH discovery pass (PRD §11): broaden constituents via Gemini Deep Research,
entity-resolve them against the existing blueprint, and attribute each to a Source.

The discovered companies are merged into the blueprint (de-duplicated by ticker/alias),
each carries a source_url, and a Source row is created per distinct citation.
"""

from __future__ import annotations

from services.engine.blueprint.coverage import summarize
from services.engine.blueprint.dedupe import (
    dedupe_companies,
    merge_companies,
    normalize_ticker,
)
from services.engine.blueprint.generate import _extract_json
from services.engine.blueprint.models import (
    Blueprint,
    BlueprintCompany,
    BlueprintRecord,
    DiscoveryContent,
    DiscoveryResult,
    RoundMeta,
)
from services.engine.blueprint.prompt import build_discovery_prompt
from services.engine.blueprint.repository import BlueprintRepository
from services.engine.llm.router import LLMRouter, Tier
from services.engine.themes.models import SourceCreate, Theme
from services.engine.themes.repository import ThemeRepository


def discover_companies(
    theme: Theme,
    base: BlueprintRecord,
    router: LLMRouter,
    blueprint_repo: BlueprintRepository,
    theme_repo: ThemeRepository,
    *,
    tier: Tier = Tier.RESEARCH,
) -> DiscoveryResult:
    known = sorted({normalize_ticker(c.ticker) for c in base.companies})
    raw = router.generate(tier, build_discovery_prompt(theme, known))
    content = DiscoveryContent.model_validate_json(_extract_json(raw))

    # One Source per distinct citation URL (each discovered company carries a Source).
    sources_created = 0
    seen_urls: set[str] = set()
    for company in content.companies:
        if company.source_url in seen_urls:
            continue
        seen_urls.add(company.source_url)
        theme_repo.add_source(
            theme.id,
            SourceCreate(type="report", url=company.source_url, publisher=company.source_publisher),
        )
        sources_created += 1

    incoming = [
        BlueprintCompany(**company.model_dump(exclude={"source_publisher"}))
        for company in content.companies
    ]
    merged = merge_companies(dedupe_companies(base.companies), incoming)

    version = blueprint_repo.next_version(theme.id)
    model_id = router.model_for(tier)
    meta = RoundMeta(
        round=version,
        added=merged.added,
        updated=merged.updated,
        delta=merged.added + merged.updated,
        converged=False,
        generated_by=model_id,
    )
    record = blueprint_repo.save(
        Blueprint(
            theme_id=theme.id,
            version=version,
            generated_by=model_id,
            companies=merged.companies,
            relationship_types=base.relationship_types,
            notes=base.notes,
        ),
        round_meta=meta,
    )
    return DiscoveryResult(
        discovered=len(content.companies),
        added=merged.added,
        updated=merged.updated,
        sources_created=sources_created,
        final=record,
        coverage=summarize(record),
    )
