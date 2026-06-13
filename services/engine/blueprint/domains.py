"""Backfill company website domains on a blueprint — for accurate Terminal logos.

A cheap LOW-tier call maps each company (ticker + name + country) to its primary corporate
website domain (e.g. "nvidia.com", "skhynix.com"). These are public, well-known facts, so no
web browsing is needed. The domain drives the company's logo on the canvas; a missing one
falls back to a colored monogram. Idempotent — only fills companies that don't already have a
domain, so re-running is safe and cheap.
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from services.engine.blueprint.generate import BlueprintParseError, _extract_json
from services.engine.blueprint.identity import build_ticker_index, resolve_to_known
from services.engine.blueprint.models import BlueprintCompany
from services.engine.llm.router import LLMRouter, Tier
from services.engine.prompts import registry

logger = logging.getLogger("valuegraph.engine.blueprint.domains")


class CompanyDomain(BaseModel):
    # A numeric ticker may arrive as a JSON number — coerce so it doesn't drop.
    model_config = ConfigDict(coerce_numbers_to_str=True)
    ticker: str
    domain: str | None = None


class DomainResearch(BaseModel):
    domains: list[CompanyDomain] = Field(default_factory=list)


_INSTRUCTIONS = """\
ROLE: You map listed companies to their PRIMARY corporate website domain (used to show a logo).
For EACH company below, give its main website domain as a bare host — no scheme, no "www", no
path. Examples: "nvidia.com", "samsung.com", "skhynix.com", "tsmc.com", "tel.com". If you are
not confident of the exact domain, return null rather than guessing. Use ONLY the given tickers.

OUTPUT — return ONLY this JSON (no prose, no fences):
{"domains": [{"ticker": "<ticker>", "domain": "<host or null>"}]}
"""

_DOMAINS_KEY = registry.register(
    "blueprint.domains",
    "Blueprint — company website domains",
    "Map companies to their website domain for logos (LOW tier, public recall).",
    _INSTRUCTIONS,
)


def _clean_domain(raw: str | None) -> str | None:
    """Normalize a model-returned value to a bare host, or None if it isn't one."""
    if not raw:
        return None
    host = raw.strip().lower()
    host = re.sub(r"^https?://", "", host)
    host = host.split("/")[0].removeprefix("www.").strip()
    if " " in host or "." not in host:
        return None
    return host or None


def build_domains_prompt(companies: list[BlueprintCompany]) -> str:
    lines = [registry.get(_DOMAINS_KEY), "", "COMPANIES:"]
    lines += [f"- {c.ticker} | {c.name} | {c.country}" for c in companies]
    return "\n".join(lines)


def research_company_domains(
    companies: list[BlueprintCompany],
    router: LLMRouter,
    *,
    tier: Tier = Tier.LOW,
    attempts: int = 2,
) -> dict[str, str]:
    """Return {ticker -> domain} for companies that don't already have one (best effort)."""
    targets = [c for c in companies if not c.domain]
    if not targets:
        return {}
    prompt = build_domains_prompt(targets)
    parsed: DomainResearch | None = None
    for attempt in range(attempts):
        nudge = "" if attempt == 0 else "\n\nReturn ONLY the JSON object."
        try:
            parsed = DomainResearch.model_validate_json(
                _extract_json(router.generate(tier, prompt + nudge))
            )
            break
        except (ValueError, ValidationError, BlueprintParseError) as exc:
            logger.info("domains.parse_retry attempt=%d: %s", attempt + 1, exc)
    if parsed is None:
        logger.warning("domains.failed: no parseable output after %d attempts", attempts)
        return {}

    index = build_ticker_index(companies)
    out: dict[str, str] = {}
    for item in parsed.domains:
        host = _clean_domain(item.domain)
        if host is None:
            continue
        ticker = resolve_to_known(item.ticker, index)  # raw/name -> canonical blueprint ticker
        if ticker is not None:
            out[ticker] = host
    return out


def fill_blueprint_domains(
    companies: list[BlueprintCompany], router: LLMRouter, *, tier: Tier = Tier.LOW
) -> tuple[list[BlueprintCompany], int]:
    """Fill missing domains on a company list; return (updated companies, count filled)."""
    found = research_company_domains(companies, router, tier=tier)
    filled = 0
    updated: list[BlueprintCompany] = []
    for company in companies:
        if not company.domain and company.ticker in found:
            company = company.model_copy(update={"domain": found[company.ticker]})
            filled += 1
        updated.append(company)
    return updated, filled
