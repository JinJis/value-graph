"""[M4-PUB-04] Publish: explicit human action, read-only Production, Staging isolation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from services.engine.db.artifacts import ThemeBuild, build_from_cve
from services.engine.db.tests.test_artifacts import _state
from services.engine.publish.assemble import AssembledGraph, assemble
from services.engine.publish.gate import GateReport, gate
from services.engine.publish.publish import (
    InMemoryProductionStore,
    PublishBlocked,
    publish,
)

PUBLISHED_AT = datetime(2026, 6, 1, tzinfo=UTC)


def _build() -> ThemeBuild:
    return build_from_cve(_state(), version=1)


def _gated() -> tuple[AssembledGraph, GateReport]:
    build = _build()
    assembled = assemble(build, threshold=0.5)
    report = gate(assembled, build)
    assert report.passed
    return assembled, report


def test_publish_creates_production_snapshot_terminal_reads() -> None:
    store = InMemoryProductionStore()
    assembled, report = _gated()

    snap = publish(assembled, report, store, actor="admin@vg", published_at=PUBLISHED_AT)

    assert snap.snapshot_version == 1
    assert snap.source_build_version == 1
    assert snap.published_by == "admin@vg"
    assert len(snap.edges) == 1 and len(snap.ghost_edges) == 1
    # Terminal's read-only seam reflects the published version.
    current = store.current(assembled.theme_id)
    assert current is not None and current.snapshot_version == 1
    assert current.edges[0]["supplier"] == "INTC"


def test_publish_requires_passing_gate_no_auto_publish() -> None:
    store = InMemoryProductionStore()
    build = _build()
    assembled = assemble(build, threshold=0.5)
    build.sources.pop("src-intc")  # introduce a violation
    failing = gate(assembled, build)
    assert failing.passed is False

    with pytest.raises(PublishBlocked):
        publish(assembled, failing, store, actor="admin@vg")
    assert store.current(assembled.theme_id) is None  # nothing leaked to Production


def test_publish_rejects_withheld_graph_and_empty_actor() -> None:
    store = InMemoryProductionStore()
    build = _build()
    withheld = assemble(build, threshold=0.99)  # below threshold
    report = gate(withheld, build)

    with pytest.raises(PublishBlocked):
        publish(withheld, report, store, actor="admin@vg")

    assembled, ok = _gated()
    with pytest.raises(PublishBlocked):
        publish(assembled, ok, store, actor="   ")  # not an explicit actor


def test_staging_edits_do_not_leak_to_production() -> None:
    store = InMemoryProductionStore()
    assembled, report = _gated()
    publish(assembled, report, store, actor="admin@vg", published_at=PUBLISHED_AT)

    # Mutate Staging AFTER publishing: top-level and nested.
    assembled.edges[0]["confidence"] = "TAMPERED"
    assembled.edges[0]["confidence_interval"]["low"] = 999
    assembled.companies.append({"ticker": "ZZZ", "name": "Leak"})

    current = store.current(assembled.theme_id)
    assert current is not None
    assert current.edges[0]["confidence"] == "derived"
    assert current.edges[0]["confidence_interval"]["low"] == 8
    assert all(c["ticker"] != "ZZZ" for c in current.companies)


def test_republish_versions_and_prior_snapshot_retained() -> None:
    store = InMemoryProductionStore()
    assembled, report = _gated()

    v1 = publish(assembled, report, store, actor="admin@vg", published_at=PUBLISHED_AT)
    v2 = publish(assembled, report, store, actor="admin@vg", published_at=PUBLISHED_AT)

    assert (v1.snapshot_version, v2.snapshot_version) == (1, 2)
    assert store.list_versions(assembled.theme_id) == [1, 2]
    current = store.current(assembled.theme_id)
    assert current is not None and current.snapshot_version == 2
    # Prior published version stays retrievable (immutable history).
    assert store.get(assembled.theme_id, 1) is not None


def test_terminal_reads_nothing_before_publish() -> None:
    store = InMemoryProductionStore()
    assert store.current("theme-1") is None
