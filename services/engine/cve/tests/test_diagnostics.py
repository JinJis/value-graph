"""Build diagnostics: explain why a graph is empty + what's missing."""

from __future__ import annotations

from datetime import UTC, datetime

from services.engine.blueprint.models import Blueprint, BlueprintCompany, BlueprintRecord
from services.engine.blueprint.repository import InMemoryBlueprintRepository
from services.engine.cve.diagnostics import build_diagnostics
from services.engine.cve.run_repository import DONE, InMemoryCveRunRepository
from services.engine.db.artifacts import ThemeBuild
from services.engine.db.graph_store import InMemoryGraphStore
from services.engine.financials.models import FinancialsUpsert
from services.engine.financials.repository import InMemoryFinancialsRepository
from services.engine.themes.models import SourceCreate, SourceRecord

THEME = "t1"


def _blueprint() -> BlueprintRecord:
    repo = InMemoryBlueprintRepository()
    return repo.save(
        Blueprint(
            theme_id=THEME,
            version=1,
            companies=[
                BlueprintCompany(ticker="INTC", name="Intel", country="US", role="supplier"),
                BlueprintCompany(ticker="HPQ", name="HP Inc.", country="US", role="customer"),
            ],
        )
    )


def _codes(diag) -> set[str]:  # type: ignore[no-untyped-def]
    return {f.code for f in diag.findings}


def test_no_blueprint_is_the_first_blocker() -> None:
    diag = build_diagnostics(
        theme_id=THEME,
        blueprint=None,
        sources=[],
        financials_repo=InMemoryFinancialsRepository(),
        calendar_repo=None,
        run_repo=InMemoryCveRunRepository(),
        graph_store=InMemoryGraphStore(),
    )
    assert diag.has_blueprint is False
    assert _codes(diag) == {"no_blueprint"}  # short-circuits everything else


def test_empty_graph_reports_no_run_and_missing_inputs() -> None:
    fin = InMemoryFinancialsRepository()  # nothing filled
    diag = build_diagnostics(
        theme_id=THEME,
        blueprint=_blueprint(),
        sources=[],  # no documents at all
        financials_repo=fin,
        calendar_repo=None,
        run_repo=InMemoryCveRunRepository(),
        graph_store=InMemoryGraphStore(),
    )
    codes = _codes(diag)
    assert "no_documents" in codes
    assert "missing_financials" in codes
    assert "no_run" in codes
    assert "empty_graph" in codes
    assert diag.financials.missing and diag.financials.covered == 0
    assert diag.build.total_edges == 0


def _source(storage_key: str | None) -> SourceRecord:
    create = SourceCreate(type="report", url="https://x", storage_key=storage_key)
    return SourceRecord(
        id="s1",
        theme_id=THEME,
        created_at=datetime.now(UTC),
        verification_status="unverified",
        **create.model_dump(),
    )


def test_done_run_with_zero_claims_flags_no_claims() -> None:
    runs = InMemoryCveRunRepository()
    rec = runs.start(THEME, "admin")
    runs.finish(
        rec.id, status=DONE, state={"claims": [], "documents": [], "edges": {}}
    )
    diag = build_diagnostics(
        theme_id=THEME,
        blueprint=_blueprint(),
        sources=[_source(None)],  # URL-only citation -> a citation, not a document
        financials_repo=InMemoryFinancialsRepository(),
        calendar_repo=None,
        run_repo=runs,
        graph_store=InMemoryGraphStore(),
    )
    assert diag.sources.citations == 1 and diag.sources.documents == 0
    assert diag.last_run is not None and diag.last_run.stages is not None
    assert diag.last_run.stages.claims == 0
    assert "no_claims" in _codes(diag)


def test_healthy_build_is_ready() -> None:
    fin = InMemoryFinancialsRepository()
    for t in ("INTC", "HPQ"):
        fin.upsert(FinancialsUpsert(company_ticker=t, revenue=100.0, cogs=80.0))
    graph = InMemoryGraphStore()
    graph.save_build(
        ThemeBuild(
            theme_id=THEME,
            version=2,
            created_at=datetime.now(UTC),
            companies=[{"ticker": "INTC", "name": "INTC"}],
            edges=[{"supplier": "INTC", "customer": "HPQ"}],  # 1 publishable
            gap_edges=[],
        )
    )
    runs = InMemoryCveRunRepository()
    rec = runs.start(THEME, "admin")
    runs.finish(
        rec.id,
        status=DONE,
        state={
            "claims": [{}],
            "documents": [{}],
            "edges": {"INTC->HPQ": {"reconciled": {}, "scored": {}, "estimated": False}},
        },
    )
    diag = build_diagnostics(
        theme_id=THEME,
        blueprint=_blueprint(),
        sources=[_source("k1")],
        financials_repo=fin,
        calendar_repo=None,
        run_repo=runs,
        graph_store=graph,
    )
    assert diag.build.total_edges == 1 and diag.build.meets_threshold
    assert diag.financials.missing == []
    assert "ready" in _codes(diag)
    assert diag.last_run is not None and diag.last_run.stages is not None
    assert diag.last_run.stages.scored == 1


def test_list_runs_returns_all_for_theme() -> None:
    runs = InMemoryCveRunRepository()
    first = runs.start(THEME, "admin")
    second = runs.start(THEME, "scheduled")
    runs.start("other-theme", "admin")
    listed = runs.list_runs(THEME)
    assert {r.id for r in listed} == {first.id, second.id}  # scoped to the theme
    assert len(runs.list_runs(THEME, limit=1)) == 1
