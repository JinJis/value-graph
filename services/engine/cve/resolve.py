"""S2: Entity resolution — map a mention to a canonical Company.

Pipeline: dictionary (exact, normalized) -> similarity candidates -> optional LLM
adjudication. When confidence is insufficient the mention is left AMBIGUOUS / UNKNOWN
(never a silent guess); the caller turns those into resolution tickets.

The similarity backend is a protocol; the default is a lightweight token metric that
also handles localized aliases via the dictionary. Real Gemini embeddings + a vector
DB (pgvector / Pinecone) plug in behind ``Similarity`` later (PRD open issue #3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field

from services.engine.llm.router import LLMRouter, Tier
from services.engine.tickets.models import TicketCreate
from services.engine.tickets.repository import TicketRepository

# Tuning (fixtures are calibrated to these).
HIGH_THRESHOLD = 0.72  # resolve outright via similarity
MARGIN = 0.10  # top candidate must beat the runner-up by this
FLOOR = 0.30  # below this, not even a candidate
TOP_K = 3

_LEGAL_SUFFIXES = {
    "corp", "corporation", "inc", "incorporated", "co", "company", "ltd", "limited",
    "plc", "ag", "sa", "nv", "llc", "group",
}


class ResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CanonicalCompany:
    ticker: str
    name: str
    aliases: tuple[str, ...] = ()

    def surface_forms(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


class Candidate(BaseModel):
    ticker: str
    score: float


class Resolution(BaseModel):
    mention: str
    status: ResolutionStatus
    ticker: str | None = None
    method: str | None = None  # dict | similarity | llm
    candidates: list[Candidate] = Field(default_factory=list)
    reason: str | None = None


def normalize(text: str) -> str:
    lowered = re.sub(r"[.,/&'’\-]", " ", text.lower().strip())
    tokens = [tok for tok in lowered.split() if tok and tok not in _LEGAL_SUFFIXES]
    return " ".join(tokens)


def token_similarity(a: str, b: str) -> float:
    """Token containment + Jaccard; robust to extra tokens (subsidiaries, suffixes)."""
    ta, tb = set(normalize(a).split()), set(normalize(b).split())
    if not ta or not tb:
        return 0.0
    if ta == tb:
        return 1.0
    inter = len(ta & tb)
    if inter == 0:
        return 0.0
    containment = inter / min(len(ta), len(tb))
    jaccard = inter / len(ta | tb)
    return 0.6 * containment + 0.4 * jaccard


class Similarity(Protocol):
    def __call__(self, a: str, b: str) -> float: ...


class Adjudicator(Protocol):
    def pick(self, mention: str, candidates: list[tuple[str, str]]) -> str | None: ...


def build_adjudicate_prompt(mention: str, candidates: list[tuple[str, str]]) -> str:
    lines = [
        "ROLE: You are an entity-resolution adjudicator.",
        f'GOAL: Which company does the mention "{mention}" refer to?',
        "CRITERIA: Choose the single best-matching ticker from the candidates below. If none "
        "clearly matches, or it is genuinely ambiguous, answer NONE — do NOT guess.",
        "",
        "CANDIDATES:",
    ]
    lines += [f"- {ticker}: {name}" for ticker, name in candidates]
    lines.append("")
    lines.append("OUTPUT: reply with ONLY the chosen ticker (exactly as written), or NONE.")
    return "\n".join(lines)


@dataclass
class LLMAdjudicator:
    """Default adjudicator: the LOW tier picks among close candidates."""

    router: LLMRouter
    tier: Tier = Tier.LOW

    def pick(self, mention: str, candidates: list[tuple[str, str]]) -> str | None:
        raw = self.router.generate(self.tier, build_adjudicate_prompt(mention, candidates))
        choice = raw.strip().splitlines()[0].strip().strip('"').upper() if raw.strip() else ""
        valid = {ticker.upper(): ticker for ticker, _ in candidates}
        return valid.get(choice)


@dataclass
class Resolver:
    companies: list[CanonicalCompany]
    similarity: Similarity = token_similarity
    adjudicator: Adjudicator | None = None
    _dict: dict[str, str] = field(default_factory=dict, init=False)
    _names: dict[str, str] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        for company in self.companies:
            self._names[company.ticker] = company.name
            for form in company.surface_forms():
                key = normalize(form)
                if key:
                    self._dict.setdefault(key, company.ticker)

    def resolve(self, mention: str) -> Resolution:
        # 1. Dictionary: exact match on a normalized name/alias.
        norm = normalize(mention)
        if norm in self._dict:
            return Resolution(
                mention=mention,
                status=ResolutionStatus.RESOLVED,
                ticker=self._dict[norm],
                method="dict",
            )

        # 2. Similarity: rank companies by their best surface-form score.
        def best_score(company: CanonicalCompany) -> float:
            return max((self.similarity(mention, f) for f in company.surface_forms()), default=0.0)

        scored = sorted(
            ((c.ticker, best_score(c)) for c in self.companies),
            key=lambda pair: pair[1],
            reverse=True,
        )
        candidates = [
            Candidate(ticker=ticker, score=round(score, 4))
            for ticker, score in scored
            if score >= FLOOR
        ][:TOP_K]
        if not candidates:
            return Resolution(
                mention=mention,
                status=ResolutionStatus.UNKNOWN,
                reason="no candidate above similarity floor",
            )

        top = candidates[0]
        runner_up = candidates[1].score if len(candidates) > 1 else 0.0
        if top.score >= HIGH_THRESHOLD and (top.score - runner_up) >= MARGIN:
            return Resolution(
                mention=mention,
                status=ResolutionStatus.RESOLVED,
                ticker=top.ticker,
                method="similarity",
                candidates=candidates,
            )

        # 3. LLM adjudication among the close candidates.
        if self.adjudicator is not None:
            pairs = [(c.ticker, self._names.get(c.ticker, c.ticker)) for c in candidates]
            choice = self.adjudicator.pick(mention, pairs)
            if choice is not None:
                return Resolution(
                    mention=mention,
                    status=ResolutionStatus.RESOLVED,
                    ticker=choice,
                    method="llm",
                    candidates=candidates,
                )

        return Resolution(
            mention=mention,
            status=ResolutionStatus.AMBIGUOUS,
            candidates=candidates,
            reason="multiple close candidates",
        )


def resolve_mentions(
    mentions: list[str],
    resolver: Resolver,
    *,
    theme_id: str | None = None,
    ticket_repo: TicketRepository | None = None,
) -> list[Resolution]:
    """Resolve each mention; open a resolution ticket for unresolved ones (no guess)."""
    results: list[Resolution] = []
    for mention in mentions:
        resolution = resolver.resolve(mention)
        results.append(resolution)
        if (
            resolution.status is not ResolutionStatus.RESOLVED
            and ticket_repo is not None
            and theme_id is not None
        ):
            candidates = [c.model_dump() for c in resolution.candidates]
            ticket_repo.create_open_ticket(
                theme_id,
                TicketCreate(
                    target=mention,
                    metric="entity-resolution",
                    reason=resolution.reason or "unresolved mention",
                    current_estimate={"candidates": candidates},
                ),
            )
    return results
