"""S1: Claim extraction (MEDIUM tier).

Extract atomic, typed, span-anchored claims from a Source's text. Hard rules
(PRD §6.2 S1): every claim carries a VERBATIM text span (no span -> no claim) and
the output validates against the canonical `Claim` schema. The claim type
(supplier-side / customer-side / absolute / qualitative) rides on `relation`,
because the graph-schema Claim is additionalProperties: false.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, ValidationError

from graph_schema import is_valid
from services.engine.llm.router import LLMRouter, Tier
from services.engine.prompts import registry

# Claim-type relations.
SUPPLIER_SHARE = "supplier_revenue_share"
CUSTOMER_SHARE = "customer_cost_share"
ABSOLUTE = "absolute_trade_value"
QUALITATIVE = "qualitative"

_INSTRUCTIONS = f"""\
ROLE: You are a precise financial-disclosure extractor.
GOAL: From the DOCUMENT below, extract atomic supply-chain claims — each ONE fact about a
single supplier->customer relationship — and nothing else.

CLASSIFY each claim by `relation`:
- "{SUPPLIER_SHARE}": a % of the SUPPLIER's revenue coming from a customer (value=percent, unit "%")
- "{CUSTOMER_SHARE}": a % of the CUSTOMER's costs going to a supplier (value=percent, unit "%")
- "{ABSOLUTE}": an absolute trade value (value=amount, unit=currency e.g. "USD")
- "{QUALITATIVE}": a known relationship with NO disclosed number (value=null, unit=null)

CRITERIA (strict):
- `subject` is the SUPPLIER, `object` is the CUSTOMER (direction matters).
- `text_span` MUST be copied VERBATIM from the DOCUMENT (an exact substring you can find by
  search). No span -> drop the claim. Do NOT paraphrase, infer, or invent numbers.
- `cost_bucket` is the BUYER's accounting bucket if stated/obvious, else null.
- Extract only relationships the document actually states; skip everything else.

OUTPUT FORMAT — return ONLY this JSON object (no prose, no fences):
{{"claims": [{{"relation": "<one of the four above>", "subject": "<supplier>",
"object": "<customer>", "value": number|null, "unit": string|null,
"cost_bucket": "COGS"|"CAPEX"|"R&D"|"SG&A"|null, "text_span": "<verbatim quote>"}}]}}

EXAMPLE (document says "HP accounted for 21% of our revenue"):
{{"claims": [{{"relation": "{SUPPLIER_SHARE}", "subject": "INTC", "object": "HPQ",
"value": 21, "unit": "%", "cost_bucket": "COGS",
"text_span": "HP accounted for 21% of our revenue"}}]}}
"""

_EXTRACT_KEY = registry.register(
    "cve.extract",
    "CVE S1 — claim extraction",
    "Extract atomic, span-anchored supply-chain claims from a document (MEDIUM tier).",
    _INSTRUCTIONS,
)


class RawClaim(BaseModel):
    """One claim as returned by the model (before the engine stamps provenance)."""

    # A numeric ticker as subject/object may arrive as a JSON number — coerce to str.
    model_config = ConfigDict(coerce_numbers_to_str=True)
    relation: str
    subject: str
    object: str
    value: float | None = None
    unit: str | None = None
    cost_bucket: str | None = None
    text_span: str


class _RawClaims(BaseModel):
    claims: list[RawClaim]


class Claim(BaseModel):
    """An extracted claim with provenance (mirrors the canonical Claim schema)."""

    relation: str
    subject: str
    object: str
    value: float | None
    unit: str | None
    cost_bucket: str | None
    as_of: str
    source_id: str
    extracted_by: str
    text_span: str


def _extract_json(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found in model output")
    return text[start : end + 1]


def parse_raw_claims(text: str) -> list[RawClaim]:
    return _RawClaims.model_validate_json(_extract_json(text)).claims


def extract_claims(
    document_text: str,
    *,
    source_id: str,
    as_of: str,
    router: LLMRouter,
    tier: Tier = Tier.MEDIUM,
) -> list[Claim]:
    """Extract span-anchored, schema-valid claims from ``document_text``."""
    prompt = f"{registry.get(_EXTRACT_KEY)}\n\nDOCUMENT:\n{document_text}"
    try:
        candidates = parse_raw_claims(router.generate(tier, prompt))
    except (ValueError, ValidationError):
        nudge = prompt + "\n\nReturn ONLY valid JSON, no prose."
        candidates = parse_raw_claims(router.generate(tier, nudge))

    model_id = router.model_for(tier)
    claims: list[Claim] = []
    for candidate in candidates:
        span = candidate.text_span
        # No verbatim span -> no claim (also drops hallucinated spans).
        if not span.strip() or span not in document_text:
            continue
        claim = Claim(
            relation=candidate.relation,
            subject=candidate.subject,
            object=candidate.object,
            value=candidate.value,
            unit=candidate.unit,
            cost_bucket=candidate.cost_bucket,
            as_of=as_of,
            source_id=source_id,
            extracted_by=model_id,
            text_span=span,
        )
        # Must validate against the canonical Claim schema (drops bad cost buckets etc.).
        if not is_valid("Claim", claim.model_dump(mode="json")):
            continue
        claims.append(claim)
    return claims
