"""[M3-EXT-01] S1 claim extraction: verbatim spans, schema validity, qualitative claims."""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from graph_schema import is_valid
from services.engine.cve.extract import (
    CUSTOMER_SHARE,
    QUALITATIVE,
    SUPPLIER_SHARE,
    extract_claims,
)
from services.engine.llm.router import LLMRouter

# A small 10-K-style excerpt (the fixture "filing").
DOC = (
    "In fiscal 2025, Intel Corporation derived 21% of its revenue from Hewlett-Packard. "
    "Intel is a key supplier of processors to Hewlett-Packard's PC division. "
    "TSMC manufactures wafers for NVIDIA under a long-term agreement."
)
SHARE_SPAN = "derived 21% of its revenue from Hewlett-Packard"
QUAL_SPAN = "TSMC manufactures wafers for NVIDIA"


class FakeGenerator:
    def __init__(self, *responses: str) -> None:
        self._responses = list(responses) or [""]
        self.calls = 0

    def generate_text(self, *, model: str, prompt: str) -> str:
        response = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return response


def _router(*responses: str) -> LLMRouter:
    return LLMRouter.from_env(env={}, generator=FakeGenerator(*responses))


def _claims_json(items: list[dict[str, Any]]) -> str:
    return json.dumps({"claims": items})


def test_extracts_share_claim_with_exact_span() -> None:
    response = _claims_json(
        [
            {
                "relation": SUPPLIER_SHARE,
                "subject": "Intel",
                "object": "Hewlett-Packard",
                "value": 21,
                "unit": "%",
                "text_span": SHARE_SPAN,
            }
        ]
    )
    claims = extract_claims(DOC, source_id="src1", as_of="2025-12-31", router=_router(response))
    assert len(claims) == 1
    claim = claims[0]
    assert claim.relation == SUPPLIER_SHARE
    assert claim.value == 21.0
    assert claim.text_span in DOC  # verbatim
    assert claim.source_id == "src1"
    assert claim.as_of == "2025-12-31"
    assert claim.extracted_by  # model id stamped


def test_claim_without_span_is_dropped() -> None:
    response = _claims_json(
        [{"relation": SUPPLIER_SHARE, "subject": "Intel", "object": "HP", "text_span": ""}]
    )
    assert extract_claims(DOC, source_id="s", as_of="2025-12-31", router=_router(response)) == []


def test_hallucinated_span_is_dropped() -> None:
    response = _claims_json(
        [
            {
                "relation": SUPPLIER_SHARE,
                "subject": "Intel",
                "object": "Dell",
                "value": 50,
                "unit": "%",
                "text_span": "50% of its revenue from Dell",  # not in DOC
            }
        ]
    )
    assert extract_claims(DOC, source_id="s", as_of="2025-12-31", router=_router(response)) == []


def test_qualitative_claim_recorded() -> None:
    response = _claims_json(
        [
            {
                "relation": QUALITATIVE,
                "subject": "TSMC",
                "object": "NVIDIA",
                "value": None,
                "text_span": QUAL_SPAN,
            }
        ]
    )
    claims = extract_claims(DOC, source_id="s", as_of="2025-12-31", router=_router(response))
    assert len(claims) == 1
    assert claims[0].value is None
    assert claims[0].relation == QUALITATIVE


def test_invalid_cost_bucket_fails_schema_and_is_dropped() -> None:
    response = _claims_json(
        [
            {
                "relation": CUSTOMER_SHARE,
                "subject": "Intel",
                "object": "Hewlett-Packard",
                "value": 9.5,
                "unit": "%",
                "cost_bucket": "BOGUS",  # not a valid CostBucket
                "text_span": SHARE_SPAN,
            }
        ]
    )
    assert extract_claims(DOC, source_id="s", as_of="2025-12-31", router=_router(response)) == []


def test_all_outputs_validate_against_claim_schema() -> None:
    response = _claims_json(
        [
            {
                "relation": SUPPLIER_SHARE,
                "subject": "Intel",
                "object": "Hewlett-Packard",
                "value": 21,
                "unit": "%",
                "cost_bucket": "COGS",
                "text_span": SHARE_SPAN,
            },
            {
                "relation": QUALITATIVE,
                "subject": "TSMC",
                "object": "NVIDIA",
                "text_span": QUAL_SPAN,
            },
        ]
    )
    claims = extract_claims(DOC, source_id="s", as_of="2025-12-31", router=_router(response))
    assert len(claims) == 2
    assert all(is_valid("Claim", c.model_dump(mode="json")) for c in claims)


def test_retry_then_parse() -> None:
    good = _claims_json(
        [{"relation": QUALITATIVE, "subject": "TSMC", "object": "NVIDIA", "text_span": QUAL_SPAN}]
    )
    claims = extract_claims(DOC, source_id="s", as_of="2025-12-31", router=_router("garbage", good))
    assert len(claims) == 1


@pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"),
    reason="no GOOGLE_API_KEY; skipping live MEDIUM extraction",
)
def test_live_extraction_spans_are_verbatim() -> None:
    claims = extract_claims(DOC, source_id="s", as_of="2025-12-31", router=LLMRouter.from_env())
    assert claims
    assert all(c.text_span in DOC for c in claims)
    assert all(is_valid("Claim", c.model_dump(mode="json")) for c in claims)
