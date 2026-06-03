"""[M6-FEED-04] Feed ingestion: entity-link raw context items to companies.

Entity linking is rule-based + deterministic here (ticker/name/alias mention), with a
clean seam for an LLM tagging pass (LOW tier) later. We only LINK items to nodes; we
never SCORE, rank by momentum, or forecast — the feed surfaces raw context (CLAUDE.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from services.pipeline.feed.models import FeedItemCreate
from services.pipeline.feed.repository import FeedRepository

_NON_WORD = re.compile(r"[^a-z0-9 ]+")
_LEGAL = {"inc", "corp", "corporation", "co", "ltd", "plc", "ag", "sa", "nv", "the"}


def _normalize(text: str) -> str:
    cleaned = _NON_WORD.sub(" ", text.lower())
    tokens = [t for t in cleaned.split() if t and t not in _LEGAL]
    return " ".join(tokens)


@dataclass(frozen=True)
class CompanyEntity:
    ticker: str
    name: str
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def surface_forms(self) -> tuple[str, ...]:
        return (self.ticker, self.name, *self.aliases)


def _mentions(haystack: str, form: str) -> bool:
    needle = _normalize(form)
    if not needle:
        return False
    # Word-boundary containment on normalized token streams.
    return re.search(rf"(?:^| ){re.escape(needle)}(?: |$)", haystack) is not None


def link_entities(text: str, companies: list[CompanyEntity]) -> list[str]:
    """Return the tickers a context item mentions (by ticker / name / alias)."""
    haystack = _normalize(text)
    linked = {c.ticker for c in companies if any(_mentions(haystack, f) for f in c.surface_forms())}
    return sorted(linked)


def ingest_items(
    raw: list[FeedItemCreate],
    companies: list[CompanyEntity],
    repo: FeedRepository,
    *,
    theme_id: str,
) -> list[str]:
    """Entity-link each raw item (if not already linked) and persist it.

    Returns the ids of the items added (newest context enters the feed as it ingests).
    """
    added: list[str] = []
    for item in raw:
        entities = item.entities or link_entities(f"{item.title} {item.snippet or ''}", companies)
        stored = repo.add_item(theme_id, item.model_copy(update={"entities": entities}))
        added.append(stored.id)
    return added
