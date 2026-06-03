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
