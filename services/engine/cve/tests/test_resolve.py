"""[M3-ENT-02] S2 entity resolution: aliases / subsidiaries / multilingual, precision,
ambiguous -> ticket."""

from __future__ import annotations

from services.engine.cve.resolve import (
    CanonicalCompany,
    LLMAdjudicator,
    ResolutionStatus,
    Resolver,
    resolve_mentions,
)
from services.engine.llm.router import LLMRouter
from services.engine.tickets.repository import InMemoryTicketRepository

COMPANIES = [
    CanonicalCompany("INTC", "Intel", ("Intel Corporation", "INTC")),
    CanonicalCompany("HPQ", "HP Inc.", ("Hewlett-Packard", "Hewlett Packard", "HP", "HPQ")),
    CanonicalCompany("NVDA", "NVIDIA", ("NVIDIA Corporation", "NVDA")),
    CanonicalCompany("TSM", "TSMC", ("Taiwan Semiconductor", "台積電", "TSM")),
    CanonicalCompany(
        "005930", "Samsung Electronics", ("삼성전자", "Samsung Electronics Co", "SSNLF")
    ),
    CanonicalCompany("006400", "Samsung SDI", ("삼성SDI", "Samsung SDI Co")),
    CanonicalCompany("6758", "Sony", ("ソニー", "Sony Group", "Sony Corporation")),
]

# (mention, expected ticker) — aliases, subsidiaries, and multilingual names.
RESOLVABLE = [
    ("Intel", "INTC"),
    ("Intel Corporation", "INTC"),
    ("INTC", "INTC"),
    ("Hewlett-Packard", "HPQ"),
    ("HP", "HPQ"),
    ("Hewlett Packard Company", "HPQ"),
    ("NVIDIA", "NVDA"),
    ("Taiwan Semiconductor Manufacturing", "TSM"),  # similarity
    ("Hewlett-Packard's PC division", "HPQ"),  # subsidiary -> similarity
    ("삼성전자", "005930"),  # multilingual
    ("ソニー", "6758"),  # multilingual
    ("台積電", "TSM"),  # multilingual
]


class FakeGenerator:
    def __init__(self, response: str) -> None:
        self._response = response

    def generate_text(self, *, model: str, prompt: str) -> str:
        return self._response


def test_resolution_precision_at_least_90pct() -> None:
    resolver = Resolver(COMPANIES)
    correct = sum(
        1 for mention, expected in RESOLVABLE if resolver.resolve(mention).ticker == expected
    )
    assert correct / len(RESOLVABLE) >= 0.90


def test_ambiguous_mention_is_not_guessed() -> None:
    resolver = Resolver(COMPANIES)
    resolution = resolver.resolve("Samsung")  # matches both Samsung entities
    assert resolution.status is ResolutionStatus.AMBIGUOUS
    assert resolution.ticker is None
    assert {c.ticker for c in resolution.candidates} >= {"005930", "006400"}


def test_unknown_mention() -> None:
    resolution = Resolver(COMPANIES).resolve("Acme Robotics")
    assert resolution.status is ResolutionStatus.UNKNOWN
    assert resolution.ticker is None


def test_llm_adjudication_resolves_close_candidates() -> None:
    router = LLMRouter.from_env(env={}, generator=FakeGenerator("005930\n"))
    resolver = Resolver(COMPANIES, adjudicator=LLMAdjudicator(router))
    resolution = resolver.resolve("Samsung")
    assert resolution.status is ResolutionStatus.RESOLVED
    assert resolution.ticker == "005930"
    assert resolution.method == "llm"


def test_llm_adjudicator_rejects_invalid_choice() -> None:
    router = LLMRouter.from_env(env={}, generator=FakeGenerator("NONE"))
    adjudicator = LLMAdjudicator(router)
    assert adjudicator.pick("Samsung", [("005930", "Samsung Electronics")]) is None


def test_resolve_mentions_tickets_only_unresolved() -> None:
    repo = InMemoryTicketRepository()
    resolver = Resolver(COMPANIES)
    results = resolve_mentions(
        ["Intel", "Samsung", "Acme Robotics"], resolver, theme_id="t1", ticket_repo=repo
    )
    statuses = {r.mention: r.status for r in results}
    assert statuses["Intel"] is ResolutionStatus.RESOLVED

    tickets = repo.list_tickets("t1")
    assert {t.target for t in tickets} == {"Samsung", "Acme Robotics"}  # resolved one not ticketed
    assert all(t.metric == "entity-resolution" for t in tickets)
