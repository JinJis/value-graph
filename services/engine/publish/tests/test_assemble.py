"""[M4-ASM-02] Graph assembly: best-effort (gaps drawn, never withheld), schema-only edges."""

from __future__ import annotations

import logging

from services.engine.db.artifacts import ThemeBuild, build_from_cve
from services.engine.db.tests.test_artifacts import _state
from services.engine.publish.assemble import OverrideLog, assemble


def _build() -> ThemeBuild:
    # 1 publishable edge (INTC->HPQ) + 1 gap edge (TSM->NVDA) => completeness 0.5.
    return build_from_cve(_state(), version=1)


def test_assembles_when_completeness_meets_threshold() -> None:
    result = assemble(_build(), threshold=0.5)

    assert result.assembled is True
    assert result.override is None
    assert result.completeness.completeness == 0.5
    assert result.completeness.meets_threshold is True
    assert len(result.edges) == 1 and result.edges[0]["supplier"] == "INTC"
    # Gap edge is carried as a drawn ghost, not hidden.
    assert len(result.ghost_edges) == 1
    assert (result.ghost_edges[0].supplier, result.ghost_edges[0].customer) == ("TSM", "NVDA")
    # Nodes for both publishable and ghost endpoints are present.
    assert {c["ticker"] for c in result.companies} == {"INTC", "HPQ", "TSM", "NVDA"}


def test_best_effort_assembles_below_threshold() -> None:
    # Below the recommended threshold we still publish what we have — gaps are drawn, not hidden.
    result = assemble(_build(), threshold=0.7)

    assert result.assembled is True
    assert result.completeness.meets_threshold is False  # reported, but not a gate
    assert result.completeness.completeness == 0.5
    assert len(result.edges) == 1  # the verified figure is shown
    assert len(result.ghost_edges) == 1  # the gap is drawn as a ghost to fill later
    assert {c["ticker"] for c in result.companies} == {"INTC", "HPQ", "TSM", "NVDA"}


def test_below_threshold_publish_is_logged(caplog) -> None:  # type: ignore[no-untyped-def]
    override = OverrideLog(actor="admin@vg", reason="flagship launch; gaps tracked by ticket")
    with caplog.at_level(logging.INFO):
        result = assemble(_build(), threshold=0.7, override=override)

    assert result.assembled is True
    assert result.override is not None and result.override.actor == "admin@vg"
    assert len(result.edges) == 1
    # The below-threshold publish (with the override actor/reason) is audited.
    assert "best-effort assembly below threshold" in caplog.text
    assert "admin@vg" in caplog.text


def test_only_schema_valid_edges_are_admitted() -> None:
    build = _build()
    build.edges.append({"supplier": "X", "customer": "Y"})  # missing required provenance

    result = assemble(build, threshold=0.5)

    # The malformed edge is dropped and does not count toward completeness or nodes.
    assert all(e.get("supplier") != "X" for e in result.edges)
    assert "X" not in {c["ticker"] for c in result.companies}
    assert result.completeness.publishable_edges == 1


def test_empty_build_is_not_assembled() -> None:
    # A truly empty build (no figure, no gap) has nothing to show — best-effort can't help.
    build = build_from_cve(
        _state().model_copy(update={"edges": {}, "claims": []}), version=1
    )
    result = assemble(build, threshold=0.7)

    assert result.completeness.total_edges == 0
    assert result.completeness.completeness == 0.0
    assert result.assembled is False
