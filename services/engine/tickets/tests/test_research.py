"""Per-ticket Deep Research resolution: verdict outcomes, persistence, and endpoints."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from services.engine.blueprint.repository import InMemoryBlueprintRepository
from services.engine.blueprint.router import get_blueprint_repository, get_router
from services.engine.llm.router import DEFAULT_MODELS, LLMRouter, Tier
from services.engine.main import app
from services.engine.themes.models import Theme, ThemeCreate
from services.engine.themes.repository import InMemoryThemeRepository
from services.engine.themes.router import get_repository as get_theme_repository
from services.engine.themes.router import get_storage
from services.engine.tickets.models import Ticket, TicketCreate
from services.engine.tickets.repository import InMemoryTicketRepository
from services.engine.tickets.research import research_tickets_events
from services.engine.tickets.router import get_ticket_repository

THEME = "theme-1"


class ResearchFake:
    """Streams one canned JSON report per call (one call per ticket attempt)."""

    def __init__(self, *responses: str, chunk: int = 40) -> None:
        self._responses = list(responses) or [""]
        self._chunk = chunk
        self.calls = 0

    def _next(self) -> str:
        response = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return response

    def generate_text(self, *, model: str, prompt: str) -> str:
        return self._next()

    def deep_research_stream(self, *, agent: str, prompt: str) -> Iterator[dict[str, str]]:
        response = self._next()
        yield {"kind": "thought", "text": "planning the research"}
        for i in range(0, len(response), self._chunk):
            yield {"kind": "text", "text": response[i : i + self._chunk]}


def _router(gen: object) -> LLMRouter:
    return LLMRouter(gen, DEFAULT_MODELS)  # type: ignore[arg-type]


def _open_ticket(
    repo: InMemoryTicketRepository, *, target: str = "NVDA", metric: str = "revenue by customer"
) -> Ticket:
    ticket = repo.create_open_ticket(
        THEME,
        TicketCreate(target=target, metric=metric, reason=f"required data point for {target}"),
    )
    assert ticket is not None
    repo.record_event(ticket.id, None, "OPEN", "system")
    return ticket


def _theme(name: str = "AI Data Centers") -> Theme:
    return InMemoryThemeRepository().create_theme(ThemeCreate(name=name))


def _batch(*results: dict[str, object]) -> str:
    """The agent's output: one resolution per ref under a "results" array."""
    return json.dumps({"results": list(results)})


_FOUND = _batch(
    {
        "ref": "T1",
        "verdict": "found",
        "value": "21% of revenue",
        "unit": "% of revenue",
        "as_of_date": "2024-12-31",
        "confidence": "high",
        "source_url": "https://example.com/ir",
        "source_publisher": "NVIDIA IR",
        "notes": "from the 10-K",
    }
)


def test_found_persists_proposal_and_keeps_open() -> None:
    repo = InMemoryTicketRepository()
    ticket = _open_ticket(repo)
    events = list(
        research_tickets_events(_theme(), [ticket], None, _router(ResearchFake(_FOUND)), repo)
    )
    kinds = [e["event"] for e in events]

    assert kinds[0] == "model" and kinds[1] == "endpoint"
    assert events[0]["tier"] == "RESEARCH"
    assert events[0]["model"] == DEFAULT_MODELS[Tier.RESEARCH]
    assert "batch_start" in kinds and "prompt" in kinds and "chunk" in kinds
    assert kinds[-1] == "done"

    proposed = next(e for e in events if e["event"] == "proposed")
    assert proposed["ticket_id"] == ticket.id
    assert proposed["value"] == "21% of revenue"
    assert proposed["source_url"] == "https://example.com/ir"
    assert proposed["by"] == "deep-research"

    updated = repo.get_ticket(ticket.id)
    assert updated is not None
    assert updated.status == "OPEN"  # awaits human accept
    assert updated.research_proposal is not None
    assert updated.research_proposal["source_url"] == "https://example.com/ir"


def test_not_found_marks_unresolvable() -> None:
    repo = InMemoryTicketRepository()
    ticket = _open_ticket(repo)
    payload = _batch({"ref": "T1", "verdict": "not_found", "notes": "no public disclosure"})
    events = list(
        research_tickets_events(_theme(), [ticket], None, _router(ResearchFake(payload)), repo)
    )

    resolved = next(e for e in events if e["event"] == "auto_resolved")
    assert resolved["status"] == "UNRESOLVABLE" and resolved["reason_code"] == "not-found"
    updated = repo.get_ticket(ticket.id)
    assert updated is not None and updated.status == "UNRESOLVABLE"
    assert updated.reason_code == "not-found"
    history = repo.list_events(ticket.id)
    assert any(e.to_status == "UNRESOLVABLE" and e.actor == "deep-research" for e in history)


def test_not_disclosed_records_10pct_constraint() -> None:
    repo = InMemoryTicketRepository()
    ticket = _open_ticket(repo)
    payload = _batch({"ref": "T1", "verdict": "not_disclosed"})
    list(research_tickets_events(_theme(), [ticket], None, _router(ResearchFake(payload)), repo))

    updated = repo.get_ticket(ticket.id)
    assert updated is not None and updated.status == "UNRESOLVABLE"
    assert updated.reason_code == "not-disclosed"
    assert updated.current_estimate is not None
    assert updated.current_estimate["upper_bound_pct"] == 10.0  # CVE 10% rule


def test_batch_resolves_all_in_one_run() -> None:
    repo = InMemoryTicketRepository()
    t1 = _open_ticket(repo, metric="m1")
    t2 = _open_ticket(repo, metric="m2")
    payload = _batch(
        {"ref": "T1", "verdict": "paywalled"}, {"ref": "T2", "verdict": "ambiguous"}
    )
    events = list(
        research_tickets_events(_theme(), [t1, t2], None, _router(ResearchFake(payload)), repo)
    )
    kinds = [e["event"] for e in events]

    # A single research run, not one per ticket.
    assert kinds.count("prompt") == 1 and kinds.count("llm_start") == 1
    assert kinds.count("batch_start") == 1
    assert kinds.count("auto_resolved") == 2
    u1, u2 = repo.get_ticket(t1.id), repo.get_ticket(t2.id)
    assert u1 is not None and u1.status == "DEFERRED" and u1.reason_code == "paywalled"
    assert u2 is not None and u2.status == "DEFERRED" and u2.reason_code == "ambiguous"


def test_missing_result_skips_its_ticket() -> None:
    repo = InMemoryTicketRepository()
    t1 = _open_ticket(repo, metric="m1")
    t2 = _open_ticket(repo, metric="m2")
    # Agent returns only T1; T2 has no result and must be left untouched.
    payload = _batch({"ref": "T1", "verdict": "not_found"})
    events = list(
        research_tickets_events(_theme(), [t1, t2], None, _router(ResearchFake(payload)), repo)
    )
    skipped = [e for e in events if e["event"] == "skipped"]
    assert any(e["ticket_id"] == t2.id for e in skipped)
    u1, u2 = repo.get_ticket(t1.id), repo.get_ticket(t2.id)
    assert u1 is not None and u1.status == "UNRESOLVABLE"
    assert u2 is not None and u2.status == "OPEN"  # untouched


def test_found_without_source_is_downgraded() -> None:
    repo = InMemoryTicketRepository()
    ticket = _open_ticket(repo)
    payload = _batch({"ref": "T1", "verdict": "found", "value": "21%", "source_url": ""})
    events = list(
        research_tickets_events(_theme(), [ticket], None, _router(ResearchFake(payload)), repo)
    )

    assert not any(e["event"] == "proposed" for e in events)
    resolved = next(e for e in events if e["event"] == "auto_resolved")
    assert resolved["status"] == "DEFERRED" and resolved["reason_code"] == "ambiguous"
    updated = repo.get_ticket(ticket.id)
    assert updated is not None and updated.research_proposal is None  # no number without a source


def test_skipped_when_transition_not_allowed() -> None:
    repo = InMemoryTicketRepository()
    ticket = _open_ticket(repo)
    repo.set_resolution(ticket.id, "UNRESOLVABLE", "not-found")
    current = repo.get_ticket(ticket.id)
    assert current is not None
    # UNRESOLVABLE -> DEFERRED is rejected by the state machine, so paywalled is skipped.
    payload = _batch({"ref": "T1", "verdict": "paywalled"})
    events = list(
        research_tickets_events(_theme(), [current], None, _router(ResearchFake(payload)), repo)
    )
    assert any(e["event"] == "skipped" for e in events)
    again = repo.get_ticket(ticket.id)
    assert again is not None and again.status == "UNRESOLVABLE"  # unchanged


def test_parse_failure_emits_error_and_leaves_ticket() -> None:
    repo = InMemoryTicketRepository()
    ticket = _open_ticket(repo)
    # Both attempts return non-JSON → all parse attempts fail.
    events = list(
        research_tickets_events(
            _theme(), [ticket], None, _router(ResearchFake("nope", "still nope")), repo
        )
    )
    assert any(e["event"] == "error" for e in events)
    assert not any(e["event"] in ("proposed", "auto_resolved") for e in events)
    updated = repo.get_ticket(ticket.id)
    assert updated is not None and updated.status == "OPEN"  # untouched


# --- Endpoint wiring ---


class _MemStorage:
    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}

    def save(self, key: str, data: bytes) -> None:
        self._blobs[key] = data

    def load(self, key: str) -> bytes:
        return self._blobs[key]

    def exists(self, key: str) -> bool:
        return key in self._blobs


Ctx = tuple[TestClient, InMemoryThemeRepository, InMemoryTicketRepository]


@pytest.fixture
def ctx() -> Iterator[Ctx]:
    themes = InMemoryThemeRepository()
    tickets = InMemoryTicketRepository()
    blueprints = InMemoryBlueprintRepository()
    storage = _MemStorage()
    app.dependency_overrides[get_theme_repository] = lambda: themes
    app.dependency_overrides[get_ticket_repository] = lambda: tickets
    app.dependency_overrides[get_blueprint_repository] = lambda: blueprints
    app.dependency_overrides[get_storage] = lambda: storage
    yield TestClient(app), themes, tickets
    app.dependency_overrides.clear()


def _frames(text: str) -> list[dict[str, object]]:
    frames: list[dict[str, object]] = []
    for line in text.splitlines():
        if line.startswith("data:"):
            frames.append(json.loads(line[5:].strip()))
    return frames


def test_research_stream_endpoint_proposes(ctx: Ctx) -> None:
    client, themes, tickets = ctx
    theme = themes.create_theme(ThemeCreate(name="AI Data Centers"))
    ticket = tickets.create_open_ticket(theme.id, TicketCreate(target="NVDA", metric="revenue"))
    assert ticket is not None
    app.dependency_overrides[get_router] = lambda: _router(ResearchFake(_FOUND))

    resp = client.post(
        f"/themes/{theme.id}/tickets/research/stream", json={"ticket_ids": [ticket.id]}
    )
    assert resp.status_code == 200, resp.text
    events = _frames(resp.text)
    assert any(e["event"] == "proposed" for e in events)
    assert events[-1]["event"] == "done"

    updated = tickets.get_ticket(ticket.id)
    assert updated is not None and updated.research_proposal is not None


def test_dismiss_clears_proposal(ctx: Ctx) -> None:
    client, themes, tickets = ctx
    theme = themes.create_theme(ThemeCreate(name="AI Data Centers"))
    ticket = tickets.create_open_ticket(theme.id, TicketCreate(target="NVDA", metric="revenue"))
    assert ticket is not None
    tickets.set_research_proposal(ticket.id, {"value": "21%", "source_url": "https://x"})

    resp = client.post(f"/tickets/{ticket.id}/research/dismiss")
    assert resp.status_code == 200, resp.text
    assert resp.json()["research_proposal"] is None
    updated = tickets.get_ticket(ticket.id)
    assert updated is not None and updated.research_proposal is None


def test_evidence_upload_clears_proposal(ctx: Ctx) -> None:
    client, themes, tickets = ctx
    theme = themes.create_theme(ThemeCreate(name="AI Data Centers"))
    ticket = tickets.create_open_ticket(theme.id, TicketCreate(target="NVDA", metric="revenue"))
    assert ticket is not None
    tickets.set_research_proposal(ticket.id, {"value": "21%", "source_url": "https://x"})

    # Accepting a proposal = uploading the cited URL as evidence (-> SUBMITTED).
    resp = client.post(
        f"/tickets/{ticket.id}/evidence",
        data={"url": "https://example.com/ir", "type": "report"},
    )
    assert resp.status_code == 201, resp.text
    updated = tickets.get_ticket(ticket.id)
    assert updated is not None and updated.status == "SUBMITTED"
    assert updated.research_proposal is None  # cleared on accept
