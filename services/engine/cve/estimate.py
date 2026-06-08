"""S5: VSCA-est (DEEP) — estimate suspected-but-unquantified edges.

A qualitative-only relationship (a link with no disclosed number) is estimated via
peer analogy / capacity / priors. The result is ALWAYS tagged `estimated` (never
higher), carries a WIDE interval, and auto-generates a ticket to get real evidence
(PRD §6.2 S5).
"""

from __future__ import annotations

from pydantic import BaseModel, ValidationError

from services.engine.cve.reconcile import Interval
from services.engine.llm.router import LLMRouter, Tier
from services.engine.prompts import registry
from services.engine.tickets.models import TicketCreate
from services.engine.tickets.repository import TicketRepository

# An estimate's interval must be at least this fraction of the point value wide.
MIN_REL_WIDTH = 0.5

_INSTRUCTIONS = """\
ROLE: You are a supply-chain estimator producing an explicitly UNCERTAIN figure.
GOAL: A supplier->customer relationship is SUSPECTED but its size is NOT disclosed anywhere.
Estimate the requested metric so the graph can draw the edge as an honest estimate.

METHOD (pick the one you used):
- "peer": analogy to comparable disclosed relationships.
- "capacity": production/shipment capacity or known volumes.
- "prior": industry base rates / structural priors.

CRITERIA:
- This is an ESTIMATE, never a fact: give an honestly WIDE [low, high] range that reflects
  real uncertainty — do NOT pretend precision. `low` <= `value` <= `high`, all non-negative.
- Base it on the supplier, customer, product/role, and any peer references provided.

OUTPUT FORMAT — return ONLY this JSON object (no prose, no fences):
{"value": number, "low": number, "high": number,
"method": "peer"|"capacity"|"prior", "rationale": "<one short sentence>"}

EXAMPLE:
{"value": 8, "low": 4, "high": 14, "method": "peer",
"rationale": "comparable foundry customers disclose 5-15% cost share"}
"""

_ESTIMATE_KEY = registry.register(
    "cve.estimate",
    "CVE S5 — VSCA estimate",
    "Estimate a suspected-but-undisclosed trade with a wide interval (DEEP tier).",
    _INSTRUCTIONS,
)


class RawEstimate(BaseModel):
    value: float
    low: float
    high: float
    method: str = "prior"
    rationale: str | None = None


class EdgeEstimate(BaseModel):
    supplier: str
    customer: str
    metric: str
    point: float
    interval: Interval
    confidence: str = "estimated"  # never higher than estimated
    method: str
    rationale: str | None = None


def build_estimate_prompt(
    supplier: str, customer: str, product: str | None, metric: str, peers: list[str] | None
) -> str:
    lines = [
        registry.get(_ESTIMATE_KEY),
        "",
        f"SUPPLIER: {supplier}",
        f"CUSTOMER: {customer}",
        f"METRIC TO ESTIMATE: {metric}",
    ]
    if product:
        lines.append(f"PRODUCT/ROLE: {product}")
    if peers:
        lines.append("PEER REFERENCES: " + "; ".join(peers))
    return "\n".join(lines)


def _extract_json(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found in model output")
    return text[start : end + 1]


def widen(value: float, low: float, high: float, min_rel_width: float = MIN_REL_WIDTH) -> Interval:
    """Guarantee a wide interval that contains ``value`` (and stays non-negative)."""
    lo, hi = min(low, high), max(low, high)
    lo, hi = min(lo, value), max(hi, value)  # point must be inside
    min_width = abs(value) * min_rel_width
    if hi - lo < min_width:
        half = min_width / 2
        lo, hi = value - half, value + half
    return Interval(low=max(lo, 0.0), high=hi)


def estimate_edge(
    *,
    supplier: str,
    customer: str,
    metric: str,
    router: LLMRouter,
    product: str | None = None,
    peers: list[str] | None = None,
    tier: Tier = Tier.DEEP,
    theme_id: str | None = None,
    ticket_repo: TicketRepository | None = None,
    min_rel_width: float = MIN_REL_WIDTH,
) -> EdgeEstimate:
    prompt = build_estimate_prompt(supplier, customer, product, metric, peers)
    try:
        raw = RawEstimate.model_validate_json(_extract_json(router.generate(tier, prompt)))
    except (ValueError, ValidationError):
        nudge = prompt + "\n\nReturn ONLY valid JSON."
        raw = RawEstimate.model_validate_json(_extract_json(router.generate(tier, nudge)))

    estimate = EdgeEstimate(
        supplier=supplier,
        customer=customer,
        metric=metric,
        point=raw.value,
        interval=widen(raw.value, raw.low, raw.high, min_rel_width),
        confidence="estimated",  # always — never higher
        method=raw.method,
        rationale=raw.rationale,
    )

    # Estimated edges always get a ticket: they need sourced evidence.
    if ticket_repo is not None and theme_id is not None:
        ticket_repo.create_open_ticket(
            theme_id,
            TicketCreate(
                target=f"{supplier}->{customer}",
                metric=f"estimate:{metric}",
                reason=f"estimated ({raw.method}); needs sourced evidence",
                current_estimate={
                    "point": estimate.point,
                    "interval": estimate.interval.model_dump(),
                    "method": estimate.method,
                },
            ),
        )
    return estimate
