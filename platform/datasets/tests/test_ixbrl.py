"""PH-PROV2: deterministic iXBRL fact→location matcher tests (pure, no network)."""

from app.providers.us.ixbrl import build_pointers_for_filing, normalize_value

# A tiny but realistic inline-XBRL doc: a statement-face table + a note table that
# DUPLICATES the current revenue, a prior-year column (same concept, other context),
# a parenthesized negative w/ sign, an instant (balance) fact, and a nil fact.
IXBRL = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<head><title>t</title></head>
<body>
<ix:header><ix:resources>
  <xbrli:context id="c-cur"><xbrli:period><xbrli:startDate>2023-10-01</xbrli:startDate><xbrli:endDate>2024-09-28</xbrli:endDate></xbrli:period></xbrli:context>
  <xbrli:context id="c-prev"><xbrli:period><xbrli:startDate>2022-10-02</xbrli:startDate><xbrli:endDate>2023-09-30</xbrli:endDate></xbrli:period></xbrli:context>
  <xbrli:context id="c-inst"><xbrli:period><xbrli:instant>2024-09-28</xbrli:instant></xbrli:period></xbrli:context>
  <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
</ix:resources></ix:header>
<table id="t-face">
  <tr><td>x</td><td>y</td><td>z</td><td>w</td><td>v</td></tr>
  <tr><td>Net sales</td>
    <td><ix:nonFraction id="f-rev-cur" name="us-gaap:Revenues" contextRef="c-cur" unitRef="usd" scale="6" decimals="-6">391,035</ix:nonFraction></td>
    <td><ix:nonFraction id="f-rev-prev" name="us-gaap:Revenues" contextRef="c-prev" unitRef="usd" scale="6" decimals="-6">383,285</ix:nonFraction></td></tr>
  <tr><td>Operating income</td>
    <td><ix:nonFraction id="f-oi" name="us-gaap:OperatingIncomeLoss" contextRef="c-cur" unitRef="usd" scale="6" sign="-" decimals="-6">(1,234)</ix:nonFraction></td></tr>
  <tr><td>Assets</td>
    <td><ix:nonFraction id="f-assets" name="us-gaap:Assets" contextRef="c-inst" unitRef="usd" scale="6" decimals="-6">352,755</ix:nonFraction></td></tr>
  <tr><td>Goodwill</td>
    <td><ix:nonFraction id="f-nil" name="us-gaap:Goodwill" contextRef="c-inst" unitRef="usd" xsi:nil="true"></ix:nonFraction></td></tr>
</table>
<table id="t-note">
  <tr><td>Revenue (note)</td>
    <td><ix:nonFraction id="f-rev-note" name="us-gaap:Revenues" contextRef="c-cur" unitRef="usd" scale="6" decimals="-6">391,035</ix:nonFraction></td></tr>
</table>
</body></html>"""


def test_normalize_value_scale_sign_parens():
    assert normalize_value("391,035", scale=6) == 391_035_000_000.0
    assert normalize_value("(1,234)", scale=6) == -1_234_000_000.0   # parentheses ⇒ negative
    assert normalize_value("1,234", sign="-") == -1234.0             # explicit sign
    assert normalize_value("1,234.5") == 1234.5
    assert normalize_value("—") is None                             # em-dash zero → no spurious match
    assert normalize_value("n/a") is None
    assert normalize_value("") is None


def test_match_exact_concept_period_value_and_locator():
    targets = [{"concept": "us-gaap:Revenues", "report_period": "2024-09-28", "value": 391_035_000_000.0}]
    [p] = build_pointers_for_filing(IXBRL, targets)
    assert p["status"] == "matched"
    assert p["element_id"] == "f-rev-cur"          # statement face, not the note duplicate
    assert p["match_rule"] == "exact"


def test_prior_year_column_disambiguated_by_period():
    targets = [{"concept": "us-gaap:Revenues", "report_period": "2023-09-30", "value": 383_285_000_000.0}]
    [p] = build_pointers_for_filing(IXBRL, targets)
    assert p["status"] == "matched" and p["element_id"] == "f-rev-prev"


def test_parenthesized_negative_with_sign_and_instant_context():
    targets = [
        {"concept": "us-gaap:OperatingIncomeLoss", "report_period": "2024-09-28", "value": -1_234_000_000.0},
        {"concept": "us-gaap:Assets", "report_period": "2024-09-28", "value": 352_755_000_000.0},
    ]
    oi, assets = build_pointers_for_filing(IXBRL, targets)
    assert oi["status"] == "matched" and oi["element_id"] == "f-oi"
    assert assets["status"] == "matched" and assets["element_id"] == "f-assets"  # instant period


def test_miss_when_no_matching_fact():
    targets = [
        {"concept": "us-gaap:Goodwill", "report_period": "2024-09-28", "value": 5_000_000_000.0},  # only a nil tag
        {"concept": "us-gaap:NotPresent", "report_period": "2024-09-28", "value": 1.0},
    ]
    for p in build_pointers_for_filing(IXBRL, targets):
        assert p["status"] == "miss" and p["element_id"] is None  # never fabricated


IXBRL_DIM = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:xbrldi="http://xbrl.org/2006/xbrldi">
<body>
<ix:header><ix:resources>
  <xbrli:context id="c-cons"><xbrli:period><xbrli:startDate>2023-10-01</xbrli:startDate><xbrli:endDate>2024-09-28</xbrli:endDate></xbrli:period></xbrli:context>
  <xbrli:context id="c-seg"><xbrli:entity><xbrli:segment><xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">us-gaap:ProductMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity><xbrli:period><xbrli:startDate>2023-10-01</xbrli:startDate><xbrli:endDate>2024-09-28</xbrli:endDate></xbrli:period></xbrli:context>
  <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
</ix:resources></ix:header>
<table id="big"><tr><td>a</td><td>b</td><td>c</td><td>d</td><td>e</td></tr>
  <tr><td>Segment revenue</td><td><ix:nonFraction id="f-seg" name="us-gaap:Revenues" contextRef="c-seg" unitRef="usd" scale="6">100</ix:nonFraction></td></tr></table>
<p>Consolidated: <ix:nonFraction id="f-cons" name="us-gaap:Revenues" contextRef="c-cons" unitRef="usd" scale="6">100</ix:nonFraction></p>
</body></html>"""


def test_prefers_consolidated_over_segment_dimension():
    # same concept/period/value in a per-segment (dimensional) context inside a BIG table
    # and a consolidated (non-dimensional) context outside any table → pick consolidated,
    # since companyfacts reports the consolidated total (PH-PROV2b hardening).
    targets = [{"concept": "us-gaap:Revenues", "report_period": "2024-09-28", "value": 100_000_000.0}]
    [p] = build_pointers_for_filing(IXBRL_DIM, targets)
    assert p["status"] == "matched" and p["element_id"] == "f-cons"


def test_unavailable_when_no_inline_xbrl():
    targets = [{"concept": "us-gaap:Revenues", "report_period": "2024-09-28", "value": 1.0}]
    [p] = build_pointers_for_filing("<html><body><p>old filing, no iXBRL</p></body></html>", targets)
    assert p["status"] == "unavailable"


def test_factlocation_upsert_and_lookup_roundtrip():
    from datetime import date

    from app.store.locations_ingest import _upsert, lookup_location

    rows = [{
        "market": "US", "cik": "320193", "accession_number": "0000320193-24-000123",
        "concept": "Revenues", "period": "annual", "report_period": date(2024, 9, 28),
        "value": 391_035_000_000.0, "unit": "USD", "primary_doc_url": "https://sec.gov/x.htm",
        "element_id": "f-rev-cur", "selector": None, "scale": 6, "sign": None,
        "match_rule": "exact", "status": "matched",
    }]
    assert _upsert(rows) == 1
    assert _upsert(rows) == 1  # idempotent — updates in place, no duplicate
    # /evidence lookup accepts the prefixed concept + ISO date and finds the matched row
    loc = lookup_location("US", "0000320193-24-000123", "us-gaap:Revenues", "2024-09-28", cik="320193")
    assert loc is not None and loc.element_id == "f-rev-cur"
    assert lookup_location("US", "0000320193-24-000123", "us-gaap:Nope", date(2024, 9, 28)) is None


def test_lookup_location_candidate_concept_list():
    from datetime import date

    from app.store.locations_ingest import _upsert, lookup_location

    def row(concept, eid):
        return {"market": "US", "cik": "320193", "accession_number": "acc-cand",
                "concept": concept, "period": "annual", "report_period": date(2024, 9, 28),
                "value": 1.0, "unit": "USD", "primary_doc_url": "https://x", "element_id": eid,
                "selector": None, "scale": 0, "sign": None, "match_rule": "exact", "status": "matched"}
    _upsert([row("Revenues", "f-revenues"), row("SalesRevenueNet", "f-sales")])
    # the filer used "Revenues" — a candidate list tries each in order and returns the match
    loc = lookup_location("US", "acc-cand",
                          "RevenueFromContractWithCustomerExcludingAssessedTax,Revenues,SalesRevenueNet",
                          "2024-09-28")
    assert loc is not None and loc.element_id == "f-revenues"
    assert lookup_location("US", "acc-cand", "Nope,AlsoNope", date(2024, 9, 28)) is None
