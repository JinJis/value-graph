"""Canonical filing links — the *specific filing page* a figure came from, not a bare
directory listing. A derived number (a ratio, a metric) must point at the exact filing
that produced its inputs, so the user can verify "정말 거기 그렇게 써 있다".

US (SEC) → the filing **index page** (`…/{accn}-index.htm`, needs CIK) — a human-readable
page listing the filing's documents, not the raw `…/{accn}/` directory.
KR (DART) → the `rcpNo` viewer (`dsaf001/main.do?rcpNo=…`) — deterministic from the receipt
number alone (DART's accession), no CIK needed.
"""

from __future__ import annotations


def sec_index_url(cik: str | int | None, accession: str | None) -> str | None:
    """SEC filing index page from CIK + accession (dashed or not)."""
    if not accession or cik in (None, ""):
        return None
    nodash = accession.replace("-", "")
    if len(nodash) != 18:
        return None
    dashed = accession if "-" in accession else f"{nodash[:10]}-{nodash[10:12]}-{nodash[12:]}"
    try:
        cik_int = int(cik)
    except (TypeError, ValueError):
        return None
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{nodash}/{dashed}-index.htm"


def dart_url(accession: str | None) -> str | None:
    """DART filing viewer from the receipt number (rcpNo = DART's accession)."""
    accession = (accession or "").strip()
    return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={accession}" if accession else None


def filing_link(market: str | None, accession: str | None, cik: str | int | None = None) -> str | None:
    """Canonical link to the specific filing an accession identifies, by market."""
    if not accession:
        return None
    m = (market or "").upper()
    if m == "KR":
        return dart_url(accession)
    if m == "US":
        return sec_index_url(cik, accession)
    return None
