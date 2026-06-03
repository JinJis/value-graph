"""[M4-PERSIST-01] In-memory graph store: versioning + full-build round-trip."""

from __future__ import annotations

from datetime import UTC, datetime

from services.engine.db.graph_store import InMemoryGraphStore, claim_key
from services.engine.db.persist import persist_cve_run
from services.engine.db.tests.test_artifacts import _state

CREATED = datetime(2026, 6, 1, tzinfo=UTC)


def test_persist_allocates_and_reconstructs_a_build() -> None:
    store = InMemoryGraphStore()
    state = _state()

    build = persist_cve_run(state, store, created_at=CREATED)
    assert build.version == 1

    loaded = store.load_build("theme-1", 1)
    assert loaded is not None
    # A theme's full state is reconstructable from the store.
    assert loaded.model_dump() == build.model_dump()
    assert len(loaded.edges) == 1 and len(loaded.gap_edges) == 1
    assert set(loaded.sources) == {"src-intc", "src-tsm"}


def test_versions_increment_and_are_retrievable() -> None:
    store = InMemoryGraphStore()
    state = _state()

    first = persist_cve_run(state, store, created_at=CREATED)
    second = persist_cve_run(state, store, created_at=CREATED)

    assert first.version == 1 and second.version == 2
    assert store.list_versions("theme-1") == [1, 2]
    latest = store.load_latest("theme-1")
    assert latest is not None and latest.version == 2
    # Prior build remains retrievable (versioned snapshots).
    assert store.load_build("theme-1", 1) is not None


def test_unknown_theme_and_version() -> None:
    store = InMemoryGraphStore()
    assert store.load_latest("nope") is None
    assert store.load_build("nope", 1) is None
    assert store.list_versions("nope") == []
    assert store.next_version("nope") == 1


def test_claim_key_is_deterministic_and_content_bound() -> None:
    a = {"source_id": "s1", "relation": "x", "subject": "A", "object": "B", "text_span": "q"}
    b = dict(a, text_span="different")
    assert claim_key(a) == claim_key(dict(a))
    assert claim_key(a) != claim_key(b)
