"""Deterministic SEC inline-XBRL fact → document-location matcher (PH-PROV2).

Pure functions. Given the primary inline-XBRL (iXBRL) HTML of a filing plus the
``(concept, period_end, value, unit)`` facts we already hold from the companyfacts API,
find the EXACT ``<ix:nonFraction>`` element that renders each fact and return a stable
locator (the element ``id`` if present, else an XPath). No fuzzy search, no LLM: the
displayed text is normalized (commas / currency / parentheses-negatives / ``sign`` /
``scale``) and matched exactly, so "this number → its place in the filing" is provable.

This is the trust engine's core: the LLM produces the number (API = source of truth);
this module maps it to where it literally appears in the real document.
"""

from __future__ import annotations

import re

from lxml import etree

# iXBRL / XBRL namespaces (matched by local-name so prefix variance doesn't matter).
_IX_FACT = "nonFraction"          # <ix:nonFraction name=… contextRef=… unitRef=… scale=… sign=…>
_CTX = "context"                  # <xbrli:context id=…><period>…
_UNIT = "unit"                    # <xbrli:unit id=…><measure>iso4217:USD

_NUM_CLEAN = re.compile(r"[,\s  $₩€%]")
_DASH = {"", "-", "—", "–", "‑", "—", "–"}


def _ln(el) -> str:
    """Local tag name (namespace- and prefix-agnostic), '' for comments/PIs."""
    if not isinstance(el.tag, str):
        return ""
    return etree.QName(el).localname


def _norm_concept(name: str | None) -> str:
    """'us-gaap:Revenues' → 'Revenues' (case preserved — concepts are case-sensitive)."""
    return name.split(":")[-1].strip() if name else ""


def normalize_value(text: str | None, scale: int = 0, sign: str | None = None) -> float | None:
    """iXBRL displayed text → the actual numeric value.

    Handles thousands commas, currency glyphs, NBSP, parenthesized negatives, an explicit
    ``sign="-"``, and the ``scale`` exponent (value × 10**scale). Returns None for blanks
    / em-dash zeros / non-numeric text (so they never spuriously match)."""
    if text is None:
        return None
    t = text.strip()
    if t in _DASH:
        return None
    neg = t.startswith("(") and t.endswith(")")
    if neg:
        t = t[1:-1]
    t = _NUM_CLEAN.sub("", t)
    if not re.fullmatch(r"-?\d+(\.\d+)?", t):
        return None
    val = float(t) * (10 ** scale)
    if neg or sign == "-":
        val = -abs(val)
    return val


def parse(html: str) -> etree._Element | None:
    """Tolerant parse of filing HTML/XHTML into an element tree (recovering parser)."""
    if not html:
        return None
    data = html.encode("utf-8") if isinstance(html, str) else html
    try:
        return etree.fromstring(data, etree.XMLParser(recover=True, huge_tree=True))
    except etree.XMLSyntaxError:
        return None


def _index_contexts(root) -> dict[str, dict]:
    """contextRef id → {end, start?, instant} from <xbrli:context><period>."""
    out: dict[str, dict] = {}
    for el in root.iter():
        if _ln(el) != _CTX:
            continue
        cid = el.get("id")
        if not cid:
            continue
        info: dict = {}
        for period in (c for c in el if _ln(c) == "period"):
            for c in period:
                ln, txt = _ln(c), (c.text or "").strip()
                if ln == "instant":
                    info["end"], info["instant"] = txt, True
                elif ln == "endDate":
                    info["end"] = txt
                elif ln == "startDate":
                    info["start"] = txt
        if info.get("end"):
            out[cid] = info
    return out


def _index_units(root) -> dict[str, str]:
    """unitRef id → measure local-name (USD, shares, pure)."""
    out: dict[str, str] = {}
    for el in root.iter():
        if _ln(el) != _UNIT:
            continue
        uid = el.get("id")
        measure = next((m for m in el.iter() if _ln(m) == "measure"), None)
        if uid and measure is not None and measure.text:
            out[uid] = measure.text.split(":")[-1].strip()
    return out


def _table_size(el) -> int:
    """Descendant count of the nearest <table> ancestor — bigger = statement face,
    smaller/none = a note repeat. Used to prefer the primary table on ties."""
    node = el.getparent()
    while node is not None:
        if _ln(node) == "table":
            return sum(1 for _ in node.iter())
        node = node.getparent()
    return 0


def _value_eq(a: float, b: float) -> bool:
    return abs(a - b) <= max(1.0, abs(b) * 1e-6)


def _selector(root, el) -> tuple[str | None, str | None]:
    """(element_id, xpath). Prefer the element's own id (robust across browser DOMs)."""
    eid = el.get("id")
    try:
        xpath = root.getroottree().getpath(el)
    except Exception:  # noqa: BLE001
        xpath = None
    return eid, xpath


def build_pointers_for_filing(html: str, targets: list[dict]) -> list[dict]:
    """Locate each target fact in the iXBRL doc.

    ``targets``: ``[{concept, report_period, value, unit?}]`` (as held from companyfacts).
    Returns one pointer per target: ``{concept, report_period, value, unit, status,
    element_id, selector, scale, sign, match_rule}``. ``status`` ∈ matched | miss |
    unavailable (no inline-XBRL facts in the document at all — older filings)."""
    root = parse(html)
    if root is None:
        return [{**t, "status": "unavailable"} for t in targets]

    contexts = _index_contexts(root)
    units = _index_units(root)

    # Pre-scan every inline fact once: concept → list of candidate elements w/ resolved meta.
    # `order` = document order (cheap, stable tiebreak — avoids per-candidate getpath).
    candidates: dict[str, list[dict]] = {}
    seen_any = False
    for order, el in enumerate(root.iter()):
        if _ln(el) != _IX_FACT:
            continue
        seen_any = True
        if el.get("nil") in ("true", "1"):
            continue
        concept = _norm_concept(el.get("name"))
        if not concept:
            continue
        try:
            scale = int(el.get("scale") or 0)
        except ValueError:
            scale = 0
        sign = el.get("sign")
        ctx = contexts.get(el.get("contextRef") or "", {})
        val = normalize_value("".join(el.itertext()), scale, sign)
        if val is None:
            continue
        candidates.setdefault(concept, []).append({
            "el": el, "order": order, "value": val, "scale": scale, "sign": sign,
            "end": ctx.get("end"), "start": ctx.get("start"),
            "unit": units.get(el.get("unitRef") or ""), "table": _table_size(el),
        })

    if not seen_any:
        return [{**t, "status": "unavailable"} for t in targets]

    pointers: list[dict] = []
    for t in targets:
        concept = _norm_concept(t.get("concept"))
        tgt_val = t.get("value")
        period_end = t.get("report_period")
        cands = candidates.get(concept, [])
        # 1) exact period-end + value  (kills prior-year columns and unrelated periods)
        hits = [c for c in cands if c["end"] == period_end and tgt_val is not None and _value_eq(c["value"], tgt_val)]
        rule = "exact"
        if not hits:  # 2) value-only (some contexts omit a clean period) — still exact value
            hits = [c for c in cands if tgt_val is not None and _value_eq(c["value"], tgt_val)]
            rule = "value-only"
        if not hits:
            pointers.append({**t, "status": "miss", "match_rule": None,
                             "element_id": None, "selector": None, "scale": None, "sign": None})
            continue
        # 3) disambiguate: prefer the statement face (largest table), then document order
        best = min(hits, key=lambda c: (-c["table"], c["order"]))
        eid, xpath = _selector(root, best["el"])
        pointers.append({
            **t, "status": "matched", "match_rule": rule,
            "element_id": eid, "selector": xpath, "scale": best["scale"], "sign": best["sign"],
        })
    return pointers
