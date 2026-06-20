"""Inline [n] source anchors + evidence marking (PH-4c).

Detects/places the bracketed [n] markers that keep every answer source-anchored,
and flags which citations actually *backed* the answer (evidence) vs were merely
consulted. Extracted from ``citations.py``; ``citations.py`` re-exports these and
agent.py imports has_anchors / anchor_markers / mark_evidence via that module.
"""

from __future__ import annotations

import re

from agentengine.models import Artifact, Citation

_ANCHOR_RE = re.compile(r"\[\d+\]")


def has_anchors(text: str | None) -> bool:
    """True if the prose already carries inline [n] markers (e.g. gemini wrote them)."""
    return bool(_ANCHOR_RE.search(text or ""))


def anchor_markers(indices) -> str:
    """Compact trailing anchor group: [1][2][3] (the deterministic floor when the
    model didn't place markers inline — keeps every answer source-anchored)."""
    return "".join(f"[{i}]" for i in indices if i)


def mark_evidence(cites: list[Citation], answer: str, artifacts: list[Artifact]) -> list[Citation]:
    """Flag which citations are *evidence* (actually backed the answer) vs merely
    consulted. Evidence = cited by [n] in the prose OR backs a rendered artifact.
    The Live Context shows only evidence; everything consulted stays in 도구·출처.
    When the model wrote no inline [n] at all, evidence falls back to the citations
    that actually returned data (a url / snippet / table) — never the bare labels."""
    cited = {int(m) for m in re.findall(r"\[(\d+)\]", answer or "")}
    art_tools = {a.tool for a in artifacts if a.tool}
    for c in cites:
        c.used = (c.index in cited) or (c.tool in art_tools)
    if cites and not any(c.used for c in cites):
        data_bearing = [c for c in cites if c.url or c.snippet or c.table]
        for c in (data_bearing or cites):
            c.used = True
    return cites
