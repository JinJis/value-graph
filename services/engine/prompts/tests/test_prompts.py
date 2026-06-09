"""Editable prompt registry + API: defaults, overrides, and live application."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from services.engine.cve.cost_bucket import build_cost_bucket_prompt
from services.engine.main import app
from services.engine.prompts import registry
from services.engine.prompts.repository import InMemoryPromptOverrideRepository
from services.engine.prompts.router import get_prompt_repository


@pytest.fixture(autouse=True)
def _reset_overrides() -> Iterator[None]:
    # The registry is process-global; clear any override this test set so others see defaults.
    yield
    registry.load_overrides({})
    app.dependency_overrides.clear()


def test_get_returns_default_until_overridden() -> None:
    key = "cve.extract"
    assert registry.has(key)
    default = registry.get(key)
    registry.apply_override(key, "EDITED EXTRACT PROMPT")
    assert registry.get(key) == "EDITED EXTRACT PROMPT"
    registry.clear_override(key)
    assert registry.get(key) == default


def test_override_changes_the_built_prompt() -> None:
    key = "cve.cost_bucket"
    registry.apply_override(key, "ONLY-REPLY-COGS")
    prompt = build_cost_bucket_prompt("AI Data Centers", "HBM stacks")
    assert prompt.startswith("ONLY-REPLY-COGS")  # the live build uses the override


def _client() -> TestClient:
    repo = InMemoryPromptOverrideRepository()
    app.dependency_overrides[get_prompt_repository] = lambda: repo
    return TestClient(app)


def test_api_list_set_reset_roundtrip() -> None:
    client = _client()
    key = "tickets.research"

    listed = client.get("/prompts").json()
    keys = {p["key"] for p in listed}
    assert "tickets.research" in keys and "cve.estimate" in keys  # all prompts registered
    item = next(p for p in listed if p["key"] == key)
    assert item["is_overridden"] is False and item["effective"] == item["default"]

    put = client.put(f"/prompts/{key}", json={"text": "NEW TICKET RESEARCH PROMPT"})
    assert put.status_code == 200
    body = put.json()
    assert body["is_overridden"] is True and body["effective"] == "NEW TICKET RESEARCH PROMPT"
    assert registry.get(key) == "NEW TICKET RESEARCH PROMPT"  # applied to the live engine

    got = client.get(f"/prompts/{key}").json()
    assert got["override"] == "NEW TICKET RESEARCH PROMPT"

    reset = client.delete(f"/prompts/{key}").json()
    assert reset["is_overridden"] is False
    assert registry.get(key) == item["default"]  # back to the built-in default


def test_api_rejects_unknown_key_and_empty_text() -> None:
    client = _client()
    assert client.put("/prompts/does.not.exist", json={"text": "x"}).status_code == 404
    assert client.get("/prompts/does.not.exist").status_code == 404
    assert client.put("/prompts/cve.extract", json={"text": "   "}).status_code == 400
