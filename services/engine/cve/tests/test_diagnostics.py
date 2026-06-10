"""Build diagnostics: explain why a graph is empty + what's missing."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

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


def _zero_claim_diag(state: dict[str, Any], sources: list[SourceRecord] | None = None):  # type: ignore[no-untyped-def]
    runs = InMemoryCveRunRepository()
    rec = runs.start(THEME, "admin")
    runs.finish(rec.id, status=DONE, state=state)
    return build_diagnostics(
        theme_id=THEME,
        blueprint=_blueprint(),
        sources=[_source(None)] if sources is None else sources,
        financials_repo=InMemoryFinancialsRepository(),
        calendar_repo=None,
        run_repo=runs,
        graph_store=InMemoryGraphStore(),
    )


def test_zero_claims_run_cve_only_flags_no_research() -> None:
    # No research metadata in the state == a bare 'Run CVE only'.
    diag = _zero_claim_diag({"claims": [], "documents": [], "edges": {}})
    assert diag.last_run is not None and diag.last_run.stages is not None
    assert diag.last_run.stages.claims == 0
    assert "no_research" in _codes(diag)


def test_zero_claims_research_error_flags_research_failed() -> None:
    state = {
        "claims": [],
        "documents": [],
        "edges": {},
        "research": {"ran": True, "trades_found": 0, "error": "GeminiError: 401"},
    }
    diag = _zero_claim_diag(state)
    assert diag.last_run is not None and diag.last_run.research is not None
    assert diag.last_run.research.error == "GeminiError: 401"
    assert "research_failed" in _codes(diag)


def test_zero_claims_research_ran_but_empty_flags_no_trades_found() -> None:
    state = {
        "claims": [],
        "documents": [],
        "edges": {},
        "research": {"ran": True, "trades_found": 0, "error": None},
    }
    diag = _zero_claim_diag(state)
    assert "no_trades_found" in _codes(diag)


def test_uploaded_document_not_ingested_is_flagged() -> None:
    # A file Source exists (storage_key) but the run ingested 0 documents (e.g. a scanned PDF).
    diag = _zero_claim_diag(
        {"claims": [], "documents": [], "edges": {}},
        sources=[_source("blob/key")],
    )
    assert diag.sources.documents == 1
    assert "documents_not_ingested" in _codes(diag)


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


def test_all_gap_edges_with_empty_calendar_flags_calendar() -> None:
    """The user's case: edges were derived but ALL landed as gaps (0% publishable) because the
    Disclosure Calendar is empty, so every edge lacks the required next_expected_update."""
    from services.engine.db.artifacts import GapEdge

    graph = InMemoryGraphStore()
    graph.save_build(
        ThemeBuild(
            theme_id=THEME,
            version=4,
            created_at=datetime.now(UTC),
            companies=[{"ticker": "INTC", "name": "INTC"}],
            edges=[],  # nothing publishable
            gap_edges=[
                GapEdge(
                    supplier="INTC",
                    customer="HPQ",
                    confidence="estimated",
                    freshness="gap",
                    reason="missing next_expected_update",
                )
            ],
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
            "edges": {"INTC->HPQ": {"reconciled": {}, "scored": {}, "estimated": True}},
        },
    )
    fin = InMemoryFinancialsRepository()
    for t in ("INTC", "HPQ"):
        fin.upsert(FinancialsUpsert(company_ticker=t, revenue=100.0, cogs=80.0))

    diag = build_diagnostics(
        theme_id=THEME,
        blueprint=_blueprint(),
        sources=[_source("k1")],
        financials_repo=fin,
        calendar_repo=None,  # no calendar -> calendar_covered == 0
        run_repo=runs,
        graph_store=graph,
    )
    codes = _codes(diag)
    assert diag.calendar_covered == 0
    assert diag.build.total_edges == 1 and diag.build.publishable_edges == 0
    assert "calendar_empty" in codes  # the headline cause is surfaced
    assert "estimated_no_asof" in codes  # and the estimated-edge angle
    cal = next(f for f in diag.findings if f.code == "calendar_empty")
    assert cal.level == "error"  # 0 publishable -> a blocker, not just a warning


def test_list_runs_returns_all_for_theme() -> None:
    runs = InMemoryCveRunRepository()
    first = runs.start(THEME, "admin")
    second = runs.start(THEME, "scheduled")
    runs.start("other-theme", "admin")
    listed = runs.list_runs(THEME)
    assert {r.id for r in listed} == {first.id, second.id}  # scoped to the theme
    assert len(runs.list_runs(THEME, limit=1)) == 1
