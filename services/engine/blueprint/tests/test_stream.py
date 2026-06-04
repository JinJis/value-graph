"""Streaming blueprint generation emits the right progress events and persists."""

from __future__ import annotations

from collections.abc import Iterator

from services.engine.blueprint.repository import InMemoryBlueprintRepository
from services.engine.blueprint.stream import generate_blueprint_events
from services.engine.blueprint.tests.fixtures import sample_json, sample_theme
from services.engine.llm.router import DEFAULT_MODELS, LLMRouter, Tier


class StreamingFake:
    """TextGenerator that streams a canned response in fixed-size pieces."""

    def __init__(self, *responses: str, chunk: int = 50) -> None:
        self._responses = list(responses) or [""]
        self._chunk = chunk
        self.calls = 0

    def generate_text(self, *, model: str, prompt: str) -> str:
        response = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return response

    def generate_text_stream(self, *, model: str, prompt: str) -> Iterator[str]:
        response = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        for i in range(0, len(response), self._chunk):
            yield response[i : i + self._chunk]


def _router(gen: object) -> LLMRouter:
    return LLMRouter(gen, DEFAULT_MODELS)  # type: ignore[arg-type]


def test_stream_happy_path_emits_steps_and_persists() -> None:
    gen = StreamingFake(sample_json(32))
    repo = InMemoryBlueprintRepository()
    events = list(
        generate_blueprint_events(sample_theme(), ["report.pdf (filing)"], _router(gen), repo)
    )
    kinds = [e["event"] for e in events]

    assert kinds[0] == "model"
    assert kinds[1] == "endpoint"
    assert "prompt" in kinds
    assert "chunk" in kinds  # streamed in multiple pieces
    assert kinds.count("chunk") > 1
    assert kinds[-1] == "done"

    model_ev = events[0]
    assert model_ev["tier"] == "DEEP"
    assert model_ev["model"] == DEFAULT_MODELS[Tier.DEEP]

    saved = next(e for e in events if e["event"] == "saved")
    assert saved["version"] == 1
    assert len(saved["blueprint"]["companies"]) == 32
    assert repo.get_latest(sample_theme().id) is not None


def test_stream_retries_then_succeeds() -> None:
    gen = StreamingFake("not json", sample_json(32))
    repo = InMemoryBlueprintRepository()
    events = list(
        generate_blueprint_events(sample_theme(), [], _router(gen), repo)
    )
    parse_events = [e for e in events if e["event"] == "parse"]
    assert parse_events[0]["status"] == "retry"
    assert parse_events[-1]["status"] == "ok"
    assert any(e["event"] == "saved" for e in events)


def test_stream_all_attempts_fail_emits_error() -> None:
    gen = StreamingFake("nope", "still nope")
    repo = InMemoryBlueprintRepository()
    events = list(
        generate_blueprint_events(sample_theme(), [], _router(gen), repo)
    )
    assert events[-1]["event"] == "error"
    assert not any(e["event"] == "saved" for e in events)
    assert repo.get_latest(sample_theme().id) is None


def _seed_blueprint(repo: InMemoryBlueprintRepository, theme_id: str) -> object:
    """Persist an initial v1 blueprint so refine/discover have a base."""
    import json

    from services.engine.blueprint.models import Blueprint

    content = json.loads(sample_json(32))
    record = repo.save(
        Blueprint(theme_id=theme_id, version=1, generated_by="seed", **content)
    )
    return record


def test_refine_stream_runs_rounds_and_persists() -> None:
    from services.engine.blueprint.stream import refine_blueprint_events

    theme = sample_theme()
    repo = InMemoryBlueprintRepository()
    base = _seed_blueprint(repo, theme.id)
    # Each round returns the same 32 companies → delta 0 → converges on round 1.
    gen = StreamingFake(sample_json(32))
    events = list(refine_blueprint_events(theme, base, _router(gen), repo))  # type: ignore[arg-type]
    kinds = [e["event"] for e in events]

    assert kinds[0] == "model"
    assert "round" in kinds
    assert "merged" in kinds
    assert kinds[-1] == "done"
    merged = next(e for e in events if e["event"] == "merged")
    assert merged["converged"] is True


def test_discover_stream_creates_sources_and_merges() -> None:
    import json

    from services.engine.blueprint.stream import discover_companies_events
    from services.engine.themes.repository import InMemoryThemeRepository

    theme = sample_theme()
    bp_repo = InMemoryBlueprintRepository()
    base = _seed_blueprint(bp_repo, theme.id)
    theme_repo = InMemoryThemeRepository()

    discovery = {
        "companies": [
            {
                "ticker": "6857.T",
                "name": "Advantest",
                "country": "JP",
                "exchange": "TSE",
                "role": "ATE",
                "products": ["testers"],
                "required_data_points": ["revenue by customer"],
                "source_url": "https://example.com/a",
                "source_publisher": "Example",
            }
        ]
    }
    gen = StreamingFake(json.dumps(discovery))
    events = list(
        discover_companies_events(theme, base, _router(gen), bp_repo, theme_repo)  # type: ignore[arg-type]
    )
    kinds = [e["event"] for e in events]
    assert kinds[0] == "model"
    assert any(e["event"] == "sources" and e["created"] == 1 for e in events)
    assert kinds[-1] == "done"
