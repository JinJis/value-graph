"""Deterministic KR DART disclosure-document fact → location matcher (PH-PROV2d).

The KR analog of ``providers/us/ixbrl.py``. DART exposes no PDF and no inline-XBRL;
the OpenDART ``document.xml`` API returns a ZIP of the disclosure document as
HTML-ish markup (uppercase ``<TABLE>/<TR>/<TD>`` tables, EUC-KR/UTF-8). So instead of
matching an ``<ix:nonFraction>`` element, we find the **statement row by its Korean
account label** (매출액 / 영업이익 / 자산총계 …) and the **value cell whose displayed
number equals the figure we already hold** from the financial-statements API — tried at
the unit scales DART tables actually use (원 / 천원 / 백만원 / 억원). Pure text match,
no fuzzy search, no LLM: the displayed number is normalized and matched exactly, so
"this figure → its place in the filing" stays provable.

The element is located at render time (not via a stored positional XPath): DART markup
parsed by lxml vs. rendered by Chromium diverge (implicit ``<tbody>``, tag-case), so we
re-run the match and inject a unique ``id`` the renderer can target robustly.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile

from lxml import html as lxml_html

from app.config import settings
from app.http import fetch_bytes, fetch_text

log = logging.getLogger(__name__)

_DART_UA = {"User-Agent": "Mozilla/5.0 (compatible; ValueGraphDatasets/0.1)"}
_DCM_RE = re.compile(r"node1\['dcmNo'\]\s*=\s*\"(\d+)\"")

# Normalized statement field → candidate DART account labels (account_nm), ordered.
# Keyed by the same field names the agent anchors evidence on (see agent-engine
# evidence._STATEMENT_HEADLINES) so /evidence?concept=<field> resolves directly.
KR_LABELS: dict[str, list[str]] = {
    # income statement
    "revenue": ["매출액", "수익(매출액)", "영업수익", "매출"],
    "cost_of_revenue": ["매출원가"],
    "gross_profit": ["매출총이익", "매출총이익(손실)"],
    "selling_general_and_administrative_expenses": ["판매비와관리비", "판매비및관리비"],
    "research_and_development": ["연구개발비", "경상연구개발비"],
    "operating_expense": ["영업비용"],
    "operating_income": ["영업이익", "영업이익(손실)"],
    "income_tax_expense": ["법인세비용", "법인세비용(수익)"],
    "net_income": ["당기순이익", "당기순이익(손실)", "분기순이익", "반기순이익", "당기순이익(손실금액)"],
    "earnings_per_share": ["기본주당이익", "기본주당순이익", "주당순이익"],
    "earnings_per_share_diluted": ["희석주당이익", "희석주당순이익"],
    # balance sheet
    "total_assets": ["자산총계"],
    "current_assets": ["유동자산"],
    "cash_and_equivalents": ["현금및현금성자산"],
    "inventory": ["재고자산"],
    "total_liabilities": ["부채총계"],
    "current_liabilities": ["유동부채"],
    "shareholders_equity": ["자본총계"],
    "retained_earnings": ["이익잉여금"],
    # cash-flow statement
    "net_cash_flow_from_operations": ["영업활동현금흐름", "영업활동으로인한현금흐름"],
    "net_cash_flow_from_investing": ["투자활동현금흐름", "투자활동으로인한현금흐름"],
    "net_cash_flow_from_financing": ["재무활동현금흐름", "재무활동으로인한현금흐름"],
}

# Unit scales DART statement tables use (원, 천원, 백만원, 억원). The document cell shows
# value / 10**exp, so a cell number `c` matches a full-won target `V` iff `c * 10**exp ≈ V`.
_SCALE_EXPS = (0, 3, 6, 8)

_NUM_CLEAN = re.compile(r"[,\s  ₩원$%]")
_WS = re.compile(r"\s+")
_XML_DECL = re.compile(r"^\s*<\?xml[^>]*\?>", re.IGNORECASE)
# negative markers DART uses: parentheses, minus, the △/▲ triangle, full-width minus
_NEG_PREFIX = ("△", "▲", "−", "－", "-")


def _norm_label(text: str | None) -> str:
    """Collapse whitespace + drop leading enumerators (로마숫자/번호) for label compares."""
    if not text:
        return ""
    return _WS.sub("", text)


def normalize_value(text: str | None) -> float | None:
    """DART cell text → its numeric value. Handles thousands commas, NBSP, ₩/원, an
    enclosing ``(…)`` or leading △/▲/− as negative. Returns None for blanks / dashes /
    non-numeric text so they never spuriously match."""
    if text is None:
        return None
    t = text.strip()
    if not t or t in {"-", "—", "–", "‑"}:
        return None
    neg = False
    if t.startswith("(") and t.endswith(")"):
        neg, t = True, t[1:-1].strip()
    for mark in _NEG_PREFIX:
        if t.startswith(mark):
            neg, t = True, t[len(mark):].strip()
            break
    t = _NUM_CLEAN.sub("", t)
    if not re.fullmatch(r"\d+(\.\d+)?", t):
        return None
    val = float(t)
    return -val if neg else val


def parse(markup: str) -> "lxml_html.HtmlElement | None":
    """Tolerant parse of DART document markup (lxml HTML parser → lowercased tags)."""
    if not markup:
        return None
    text = _XML_DECL.sub("", markup)  # lxml rejects a unicode str w/ an encoding decl
    try:
        return lxml_html.fromstring(text)
    except Exception:  # noqa: BLE001 — malformed doc → no evidence (graceful)
        return None


def _value_eq(a: float, b: float) -> bool:
    return abs(a - b) <= max(1.0, abs(b) * 1e-4)


def _row_cells(tr) -> list:
    """Leaf elements in a row that carry their own text (the table cells)."""
    return [el for el in tr.iter() if len(el) == 0 and (el.text or "").strip()]


def _find(root, value: float, labels: list[str]) -> tuple | None:
    """Best (element, scale_exp, label, match_rule) for ``value`` in a row whose label
    matches one of ``labels``; None if nothing matches. Prefers an exact label over a
    substring one, the largest table (statement face over a note repeat), then doc order."""
    if value is None or not labels:
        return None
    norm_labels = [(lab, _norm_label(lab)) for lab in labels if lab]
    best = None  # (rank_tuple, element, scale_exp, label, rule)
    order = 0
    for table in root.iter("table"):
        tsize = sum(1 for _ in table.iter())
        for tr in table.iter("tr"):
            order += 1
            cells = _row_cells(tr)
            if not cells:
                continue
            # label cells = the row's non-numeric cells; value cells = the numeric ones
            label_texts = {_norm_label(c.text) for c in cells if normalize_value(c.text) is None}
            row_text = _norm_label("".join(tr.itertext()))
            hit = next(((lab, "exact") for lab, nl in norm_labels if nl and nl in label_texts), None)
            if not hit:
                hit = next(((lab, "label-substr") for lab, nl in norm_labels if nl and nl in row_text), None)
            if not hit:
                continue
            label, rule = hit
            for cell in cells:
                num = normalize_value(cell.text)
                if num is None:
                    continue
                for exp in _SCALE_EXPS:
                    if _value_eq(num * (10 ** exp), value):
                        rank = (0 if rule == "exact" else 1, -tsize, order)
                        if best is None or rank < best[0]:
                            best = (rank, cell, exp, label, rule)
                        break
    if best is None:
        return None
    _, el, exp, label, rule = best
    return el, exp, label, rule


def build_pointers_for_document(markup: str, targets: list[dict]) -> list[dict]:
    """Locate each target figure in the DART document (offline precompute).

    ``targets``: ``[{concept, report_period, value, labels}]`` where ``labels`` are the
    candidate Korean account names for that field. Returns one pointer per target:
    ``{concept, report_period, value, status, scale, match_rule, label}`` with
    ``status`` ∈ matched | miss | unavailable (no parseable tables at all)."""
    root = parse(markup)
    if root is None or next(root.iter("table"), None) is None:
        return [{"concept": t.get("concept"), "report_period": t.get("report_period"),
                 "value": t.get("value"), "status": "unavailable", "scale": None,
                 "match_rule": None, "label": None} for t in targets]
    out: list[dict] = []
    for t in targets:
        found = _find(root, t.get("value"), t.get("labels") or [])
        if not found:
            out.append({"concept": t.get("concept"), "report_period": t.get("report_period"),
                        "value": t.get("value"), "status": "miss", "scale": None,
                        "match_rule": None, "label": None})
            continue
        _, exp, label, rule = found
        out.append({"concept": t.get("concept"), "report_period": t.get("report_period"),
                    "value": t.get("value"), "status": "matched", "scale": exp,
                    "match_rule": rule, "label": label})
    return out


def mark_target(markup: str, value: float, labels: list[str], element_id: str) -> str | None:
    """Re-find ``value`` (anchored on ``labels``), tag the matched cell with ``element_id``,
    and return the serialized HTML for the renderer. None if no match. Run at render time so
    the renderer locates a robust ``#id`` (not a positional XPath that diverges under Chromium)."""
    root = parse(markup)
    if root is None:
        return None
    found = _find(root, value, labels)
    if not found:
        return None
    el = found[0]
    el.set("id", element_id)
    return lxml_html.tostring(root, encoding="unicode")


async def _resolve_dcm_no(rcept_no: str) -> str | None:
    """The main document number for a receipt, from the DART viewer tree (needed by the
    official PDF endpoint). Public website — no OpenDART key required."""
    try:
        html = await fetch_text("dart", f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
                                headers=_DART_UA)
    except Exception:  # noqa: BLE001
        return None
    m = _DCM_RE.search(html)
    return m.group(1) if m else None


async def fetch_dart_pdf(rcept_no: str) -> bytes | None:
    """The OFFICIAL DART filing PDF (the full report, financials included) via the public
    ``pdf/download/pdf.do`` endpoint. Keyless and Chromium-free — this is why KR evidence
    needs no headless render. None on any failure → caller falls back to markup→render.

    NB: this is the DART website (not the OpenDART API), so it needs a Referer and may
    change; the document.xml→renderer path stays as a fallback."""
    if not rcept_no:
        return None
    dcm = await _resolve_dcm_no(rcept_no)
    if not dcm:
        log.warning("DART pdf: no dcmNo for rcept %s (viewer unreachable?) → fallback", rcept_no)
        return None
    referer = f"https://dart.fss.or.kr/pdf/download/main.do?rcp_no={rcept_no}&dcm_no={dcm}"
    url = f"https://dart.fss.or.kr/pdf/download/pdf.do?rcp_no={rcept_no}&dcm_no={dcm}"
    try:
        pdf = await fetch_bytes("dart", url, headers={**_DART_UA, "Referer": referer})
    except Exception as exc:  # noqa: BLE001
        log.warning("DART pdf fetch failed rcept=%s dcm=%s: %s", rcept_no, dcm, exc)
        return None
    if pdf[:4] != b"%PDF":
        log.warning("DART pdf: non-PDF body rcept=%s dcm=%s → fallback", rcept_no, dcm)
        return None
    log.info("DART official pdf rcept=%s dcm=%s (%d KB)", rcept_no, dcm, len(pdf) // 1024)
    return pdf


def _decode_doc(raw: bytes) -> str:
    """Decode DART document bytes (EUC-KR/CP949 historically; UTF-8 newer)."""
    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


async def fetch_document_markup(rcept_no: str) -> str | None:
    """Download the DART disclosure document (``document.xml`` API → ZIP of markup) for a
    receipt number and return its combined markup. A 사업보고서 ZIP bundles the main body
    **plus separate files** (e.g. the audited financial statements / 감사보고서) — the exact
    figure we hold often lives in one of those, not the largest file — so we concatenate
    every document file into one tree. None on any failure (no key, network, bad zip) →
    evidence then degrades to the text source card."""
    if not settings.opendart_api_key or not rcept_no:
        return None
    url = f"https://opendart.fss.or.kr/api/document.xml?crtfc_key={settings.opendart_api_key}&rcept_no={rcept_no}"
    try:
        blob = await fetch_bytes("opendart", url)
    except Exception:  # noqa: BLE001 — upstream/network → graceful (None)
        return None
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except (zipfile.BadZipFile, OSError):
        return None
    parts: list[str] = []
    with zf:
        for name in zf.namelist():
            if not name.lower().endswith((".xml", ".html", ".htm")):
                continue
            try:
                text = _decode_doc(zf.read(name))
            except (KeyError, OSError):
                continue
            text = _XML_DECL.sub("", text.lstrip())  # drop a leading <?xml …?> so it nests cleanly
            if text.strip():
                parts.append(text)
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return "<html><body>" + "\n".join(parts) + "</body></html>"
