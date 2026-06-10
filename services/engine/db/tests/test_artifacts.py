"""[M4-PERSIST-01] CVE state -> schema-valid, versioned graph artifacts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from graph_schema import is_valid
from services.engine.cve.extract import Claim
from services.engine.cve.pipeline import CVEState, EdgeResult
from services.engine.cve.reconcile import Interval, Reconciled
from services.engine.cve.score import Scored
from services.engine.db.artifacts import build_from_cve

CREATED = datetime(2026, 6, 1, tzinfo=UTC)


def _state() -> CVEState:
    claims = [
        Claim(
            relation="supplier_revenue_share",
            subject="INTC",
            object="HPQ",
            value=21,
            unit="%",
            cost_bucket="COGS",
            as_of="2026-05-20",
            source_id="src-intc",
            extracted_by="model-x",
            text_span="21% of its revenue came from HP Inc.",
        ),
        Claim(
            relation="qualitative",
            subject="TSM",
            object="NVDA",
            value=None,
            unit=None,
            cost_bucket=None,
            as_of="2026-05-22",
            source_id="src-tsm",
            extracted_by="model-x",
            text_span="TSMC supplies advanced wafers to NVIDIA",
        ),
    ]
    disclosed = EdgeResult(
        target="INTC->HPQ",
        supplier="INTC",
        customer="HPQ",
        as_of="2026-05-20",
        reconciled=Reconciled(
            point=9.5, interval=Interval(low=8, high=11), status="reconciled", n_sources=1
        ),
        scored=Scored(
            confidence="derived",
            confidence_interval=Interval(low=8, high=11),
            freshness="fresh",
            as_of_date="2026-05-20",
            next_expected_update="2026-08-15",
        ),
    )
    estimated = EdgeResult(
        target="TSM->NVDA",
        supplier="TSM",
        customer="NVDA",
        estimated=True,
        reconciled=Reconciled(
            point=8, interval=Interval(low=4, high=12), status="reconciled", n_sources=0
        ),
        scored=Scored(
            confidence="estimated",
            confidence_interval=Interval(low=4, high=12),
            freshness="gap",
            as_of_date=None,
            next_expected_update=None,
        ),
    )
    return CVEState(
        theme_id="theme-1",
        today="2026-06-01",
        claims=claims,
        financials={"INTC": {"revenue": 100.0}, "HPQ": {"COGS": 221.0}},
        edges={"INTC->HPQ": disclosed, "TSM->NVDA": estimated},
    )


def test_disclosed_edge_becomes_schema_valid_supplies_edge() -> None:
    build = build_from_cve(_state(), version=1, created_at=CREATED)

    assert build.version == 1
    assert [c["ticker"] for c in build.companies] == ["HPQ", "INTC", "NVDA", "TSM"]

    assert len(build.edges) == 1
    edge = build.edges[0]
    assert is_valid("SuppliesEdge", edge)
    assert edge["supplier"] == "INTC" and edge["customer"] == "HPQ"
    assert edge["confidence"] == "derived"
    assert edge["customer_cost_share"] == 9.5
    assert edge["cost_bucket"] == "COGS"
    # Two-ledger recovery: trade_value = 21% * Rev_INTC(100) = 21.
    assert edge["trade_value"] == 21
    assert edge["supplier_rev_share"] == 21
    assert edge["as_of_date"] == "2026-05-20"
    assert edge["next_expected_update"] == "2026-08-15"


def test_company_meta_attaches_real_name_and_logo_domain() -> None:
    meta: dict[str, dict[str, Any]] = {
        "INTC": {"name": "Intel Corporation", "domain": "intel.com"},
        "HPQ": {"name": "HP Inc.", "domain": None},  # known name, no domain
    }
    build = build_from_cve(_state(), version=1, company_meta=meta, created_at=CREATED)
    by = {c["ticker"]: c for c in build.companies}
    assert by["INTC"]["name"] == "Intel Corporation"
    assert by["INTC"]["domain"] == "intel.com"
    assert by["HPQ"]["name"] == "HP Inc." and "domain" not in by["HPQ"]
    assert by["NVDA"]["name"] == "NVDA"  # no meta -> falls back to the bare ticker


def test_edge_missing_provenance_is_a_drawn_gap_not_dropped() -> None:
    build = build_from_cve(_state(), version=1, created_at=CREATED)

    assert len(build.gap_edges) == 1
    gap = build.gap_edges[0]
    assert (gap.supplier, gap.customer) == ("TSM", "NVDA")
    assert gap.confidence == "estimated"
    assert "as_of_date" in gap.reason and "next_expected_update" in gap.reason


def test_claims_and_sources_persist() -> None:
    build = build_from_cve(_state(), version=1, created_at=CREATED)

    assert len(build.claims) == 2
    assert all(is_valid("Claim", c) for c in build.claims)
    # Sources referenced by claims get nodes (bare references by default).
    assert set(build.sources) == {"src-intc", "src-tsm"}


def test_supplied_source_records_are_validated_and_stored() -> None:
    sources = [
        {
            "id": "src-intc",
            "type": "filing",
            "url": "https://www.sec.gov/intc-10k",
            "as_of_date": "2026-05-20",
            "publisher": "SEC",
            "language": "en",
            "verification_status": "verified",
        }
    ]
    build = build_from_cve(_state(), version=2, sources=sources, created_at=CREATED)

    assert build.version == 2
    assert is_valid("Source", build.sources["src-intc"])
    assert build.sources["src-intc"]["url"] == "https://www.sec.gov/intc-10k"
    assert build.sources["src-tsm"] == {}  # not supplied -> bare reference


def test_edge_sources_link_each_figure_to_its_document() -> None:
    sources = [
        {
            "id": "src-intc",
            "type": "filing",
            "url": "https://www.sec.gov/intc-10k",
            "as_of_date": "2026-05-20",
        }
    ]
    build = build_from_cve(_state(), version=1, sources=sources, created_at=CREATED)

    # Only the admitted (publishable) edge gets source refs; the gap edge does not.
    assert set(build.edge_sources) == {"INTC->HPQ"}
    refs = build.edge_sources["INTC->HPQ"]
    assert len(refs) == 1
    assert refs[0]["source_id"] == "src-intc"
    assert refs[0]["url"] == "https://www.sec.gov/intc-10k"
    assert refs[0]["as_of_date"] == "2026-05-20"


def test_edge_details_carry_claims_and_reconciliation() -> None:
    build = build_from_cve(_state(), version=1, created_at=CREATED)

    assert set(build.edge_details) == {"INTC->HPQ"}  # admitted edges only
    detail = build.edge_details["INTC->HPQ"]

    rec = detail["reconciliation"]
    assert rec is not None
    assert rec["status"] == "reconciled"  # single-source, no conflict
    assert rec["interval"] == {"low": 8.0, "high": 11.0}
    assert rec["point"] == 9.5

    # The supporting claim travels with its verbatim span (SUPPORTS evidence).
    assert len(detail["claims"]) == 1
    claim = detail["claims"][0]
    assert claim["relation"] == "supplier_revenue_share"
    assert claim["text_span"] == "21% of its revenue came from HP Inc."
    assert claim["source_id"] == "src-intc"
