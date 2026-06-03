"""[M4-GATE-03] Validation gate: provenance violations block publish; override is logged."""

from __future__ import annotations

import logging

from services.engine.db.artifacts import ThemeBuild, build_from_cve
from services.engine.db.tests.test_artifacts import _state
from services.engine.publish.assemble import OverrideLog, assemble
from services.engine.publish.gate import gate


def _build() -> ThemeBuild:
    return build_from_cve(_state(), version=1)


def test_clean_graph_passes_the_gate() -> None:
    build = _build()
    assembled = assemble(build, threshold=0.5)

    report = gate(assembled, build)

    assert report.checked_edges == 1
    assert report.clean is True and report.passed is True
    assert report.violations == []
    assert report.override is None


def test_edge_without_source_is_flagged() -> None:
    build = _build()
    assembled = assemble(build, threshold=0.5)
    # Drop the backing Source so the INTC->HPQ figure has no provenance.
    build.sources.pop("src-intc")

    report = gate(assembled, build)

    assert report.passed is False and report.clean is False
    assert any(v.field == "source" and v.edge == "INTC->HPQ" for v in report.violations)


def test_missing_next_update_is_flagged() -> None:
    build = _build()
    assembled = assemble(build, threshold=0.5)
    assembled.edges[0]["next_expected_update"] = ""  # tamper provenance

    report = gate(assembled, build)

    assert report.passed is False
    assert any(v.field == "next_expected_update" for v in report.violations)


def test_inverted_interval_is_flagged() -> None:
    build = _build()
    assembled = assemble(build, threshold=0.5)
    assembled.edges[0]["confidence_interval"] = {"low": 11.0, "high": 8.0}

    report = gate(assembled, build)

    assert report.passed is False
    assert any(v.field == "confidence_interval" for v in report.violations)


def test_override_allows_publish_and_is_logged(caplog) -> None:  # type: ignore[no-untyped-def]
    build = _build()
    assembled = assemble(build, threshold=0.5)
    build.sources.pop("src-intc")  # create a violation
    override = OverrideLog(actor="admin@vg", reason="source link pending; tracked by ticket")

    with caplog.at_level(logging.WARNING):
        report = gate(assembled, build, override=override)

    assert report.clean is False and report.passed is True
    assert report.override is not None and report.override.actor == "admin@vg"
    assert "validation-gate override" in caplog.text


def test_unassembled_graph_never_passes() -> None:
    build = _build()
    withheld = assemble(build, threshold=0.99)  # below threshold -> withheld

    report = gate(withheld, build)

    assert withheld.assembled is False
    assert report.passed is False
    assert any(v.field == "assembly" for v in report.violations)
