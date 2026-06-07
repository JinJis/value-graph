"""Group similar tickets so one Deep Research call can resolve many at once.

Deep Research is expensive; running it per ticket (or as one giant unfocused prompt over
every open ticket) wastes calls and degrades quality. This clusters tickets with a CHEAP
model (LOW tier) — same/related company, or the same metric — so each Deep Research call
is focused and bounded. Falls back to a deterministic metric-grouping when the light model
is unavailable or returns unusable output, so clustering always works.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from services.engine.blueprint.generate import _extract_json
from services.engine.llm.router import LLMRouter, Tier
from services.engine.tickets.models import Ticket

logger = logging.getLogger("valuegraph.engine.tickets.cluster")

DEFAULT_MAX_CLUSTER_SIZE = 10


class _ClusterPlan(BaseModel):
    clusters: list[list[str]]


_INSTRUCTIONS = """\
Group data-research tasks so they can be batched efficiently. Put tickets about the SAME \
or CLOSELY RELATED company, OR the SAME metric, in the same group — so one research pass \
can answer them together. Keep groups focused (don't lump everything into one).

Return ONLY JSON: {"clusters": [["T1", "T4"], ["T2", "T3"]]}. Use each ref EXACTLY once.

TICKETS:
"""


def build_cluster_prompt(refs: dict[str, Ticket]) -> str:
    lines = [_INSTRUCTIONS]
    for ref, ticket in refs.items():
        lines.append(f"[{ref}] {ticket.target} · {ticket.metric}")
    return "\n".join(lines)


def _llm_clusters(
    ticket_list: list[Ticket], router: LLMRouter, tier: Tier
) -> list[list[Ticket]] | None:
    """Ask the light model to group the tickets; None on any failure (-> fallback)."""
    refs = {f"T{i + 1}": ticket for i, ticket in enumerate(ticket_list)}
    try:
        text = router.generate(tier, build_cluster_prompt(refs))
        plan = _ClusterPlan.model_validate_json(_extract_json(text))
    except Exception as exc:  # parse/LLM/network — fall back deterministically
        logger.warning("cluster.llm_failed: %s", exc)
        return None

    assigned: set[str] = set()
    groups: list[list[Ticket]] = []
    for cluster in plan.clusters:
        group = [refs[r] for r in cluster if r in refs and r not in assigned]
        assigned.update(r for r in cluster if r in refs)
        if group:
            groups.append(group)
    leftover = [refs[r] for r in refs if r not in assigned]  # any ref the model dropped
    if leftover:
        groups.append(leftover)
    return groups or None


def _fallback_clusters(ticket_list: list[Ticket]) -> list[list[Ticket]]:
    """Deterministic grouping by metric (same data point across companies batches well)."""
    by_metric: dict[str, list[Ticket]] = {}
    for ticket in ticket_list:
        by_metric.setdefault(ticket.metric, []).append(ticket)
    return list(by_metric.values())


def cluster_tickets(
    tickets: list[Ticket],
    router: LLMRouter,
    *,
    tier: Tier = Tier.LOW,
    max_size: int = DEFAULT_MAX_CLUSTER_SIZE,
) -> list[list[Ticket]]:
    """Return tickets grouped into focused clusters (each <= ``max_size``)."""
    ticket_list = list(tickets)
    if len(ticket_list) <= 1:
        return [ticket_list] if ticket_list else []

    groups = _llm_clusters(ticket_list, router, tier) or _fallback_clusters(ticket_list)

    # Cap each cluster so a Deep Research prompt stays bounded (cost + reliability).
    bounded: list[list[Ticket]] = []
    for group in groups:
        for start in range(0, len(group), max_size):
            bounded.append(group[start : start + max_size])
    return bounded
