"""PH-PROV2d: deterministic KR DART document fact→location matcher (pure, no network)."""

from __future__ import annotations

from app.providers.kr.dart_document import (
    build_pointers_for_document,
    mark_target,
    normalize_value,
    parse,
)

# DART-style disclosure markup: uppercase tags, a 백만원 (millions) statement table with
# current + prior columns, a parenthesized negative, and a second (balance) table.
DOC = """
<DOCUMENT>
<P>단위 : 백만원</P>
<TABLE>
<TR><TD>계정과목</TD><TD>당기</TD><TD>전기</TD></TR>
<TR><TD>매출액</TD><TD>300,870,903</TD><TD>279,604,799</TD></TR>
<TR><TD>영업이익</TD><TD>6,566,976</TD><TD>43,376,630</TD></TR>
<TR><TD>당기순이익</TD><TD>(5,000,000)</TD><TD>39,907,450</TD></TR>
</TABLE>
<TABLE>
<TR><TD>자산총계</TD><TD>448,424,507</TD><TD>426,621,158</TD></TR>
</TABLE>
</DOCUMENT>
"""

_REVENUE = 300_870_903_000_000  # 백만원 cell × 10**6
_NET_INCOME = -5_000_000_000_000
_ASSETS = 448_424_507_000_000


def test_normalize_value():
    assert normalize_value("300,870,903") == 300870903.0
    assert normalize_value("(5,000,000)") == -5000000.0   # parenthesized negative
    assert normalize_value("△1,234") == -1234.0           # triangle negative (DART)
    assert normalize_value("1,234원") == 1234.0
    assert normalize_value("-") is None and normalize_value("") is None
    assert normalize_value("계정과목") is None             # non-numeric label


def test_matches_label_anchored_at_millions_scale():
    targets = [{"concept": "revenue", "report_period": "2025-12-31", "value": _REVENUE,
                "labels": ["매출액", "수익(매출액)"]}]
    [ptr] = build_pointers_for_document(DOC, targets)
    assert ptr["status"] == "matched"
    assert ptr["scale"] == 6 and ptr["match_rule"] == "exact" and ptr["label"] == "매출액"


def test_parenthesized_negative_and_second_table():
    ptrs = build_pointers_for_document(DOC, [
        {"concept": "net_income", "report_period": "2025-12-31", "value": _NET_INCOME,
         "labels": ["당기순이익"]},
        {"concept": "total_assets", "report_period": "2025-12-31", "value": _ASSETS,
         "labels": ["자산총계"]},
    ])
    assert [p["status"] for p in ptrs] == ["matched", "matched"]


def test_miss_when_value_absent_or_label_absent():
    ptrs = build_pointers_for_document(DOC, [
        {"concept": "revenue", "report_period": "2025-12-31", "value": 999.0, "labels": ["매출액"]},
        {"concept": "gross_profit", "report_period": "2025-12-31", "value": _REVENUE,
         "labels": ["매출총이익"]},  # label not in the doc
    ])
    assert [p["status"] for p in ptrs] == ["miss", "miss"]


def test_unavailable_when_no_tables():
    [ptr] = build_pointers_for_document("<DOCUMENT><P>표지</P></DOCUMENT>",
                                        [{"concept": "revenue", "report_period": "2025-12-31",
                                          "value": _REVENUE, "labels": ["매출액"]}])
    assert ptr["status"] == "unavailable"


def test_mark_target_injects_id_on_the_matched_cell():
    html = mark_target(DOC, _REVENUE, ["매출액"], "vg-ev-test")
    assert html is not None
    root = parse(html)
    el = root.get_element_by_id("vg-ev-test")
    assert el is not None and el.text.strip() == "300,870,903"
    # no match → None (graceful; /evidence then returns 204)
    assert mark_target(DOC, 12345.0, ["매출액"], "vg-ev-test") is None
