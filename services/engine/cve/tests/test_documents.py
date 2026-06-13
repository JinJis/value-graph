"""Document ingestion (_documents): UTF-8 text and PDFs, best-effort skipping."""

from __future__ import annotations

import io
from datetime import UTC, date, datetime

from services.engine.cve.run_service import _documents, _pdf_text, _source_text
from services.engine.themes.models import SourceCreate, SourceRecord

THEME = "t1"


def _valid_pdf(text: str) -> bytes:
    """A minimal but structurally-valid PDF (real xref + startxref) with one text line."""
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
    ]
    stream = b"BT /F1 24 Tf 72 700 Td (" + text.encode() + b") Tj ET"
    objs.append(b"<</Length %d>>stream\n" % len(stream) + stream + b"\nendstream")
    objs.append(b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj" % i + body + b"endobj\n")
    xref_pos = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(
        b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF"
        % (len(objs) + 1, xref_pos)
    )
    return out.getvalue()


def test_pdf_text_extracts_a_real_text_layer() -> None:
    assert "INTC supplies HPQ" in _pdf_text(_valid_pdf("INTC supplies HPQ 21pct"))


class _Storage:
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self._blobs = blobs

    def save(self, key: str, data: bytes) -> None:  # pragma: no cover - unused
        self._blobs[key] = data

    def load(self, key: str) -> bytes:
        return self._blobs[key]

    def exists(self, key: str) -> bool:  # pragma: no cover - unused
        return key in self._blobs


def _source(
    sid: str,
    *,
    storage_key: str | None,
    content_type: str | None = None,
    filename: str | None = None,
) -> SourceRecord:
    create = SourceCreate(
        type="filing",
        url="https://x",
        storage_key=storage_key,
        content_type=content_type,
        original_filename=filename,
        as_of_date=date(2026, 5, 20),
    )
    return SourceRecord(
        id=sid,
        theme_id=THEME,
        created_at=datetime.now(UTC),
        verification_status="unverified",
        **create.model_dump(),
    )


def test_source_text_decodes_utf8_for_non_pdf() -> None:
    raw = "INTC supplies HPQ — 21% of revenue.".encode()
    src = _source("s1", storage_key="k", content_type="text/plain")
    assert _source_text(raw, src) == "INTC supplies HPQ — 21% of revenue."


def test_source_text_routes_pdf_by_magic_bytes_to_pdf_extractor() -> None:
    # A corrupt PDF (right magic, junk body) must not be UTF-8 mojibake'd into a document;
    # the PDF path returns "" (best effort), so the caller skips it.
    raw = b"%PDF-1.7\nnot a real pdf body"
    src = _source("s1", storage_key="k")  # no content_type/filename -> magic bytes decide
    assert _source_text(raw, src) == ""


def test_pdf_text_is_graceful_on_garbage() -> None:
    assert _pdf_text(b"%PDF-garbage") == ""


def test_documents_ingests_text_and_pdf_skips_empty_and_url_only() -> None:
    blobs = {
        "txt": b"INTC supplies HPQ.",
        "pdf": _valid_pdf("TSMC supplies NVDA"),  # real PDF text layer -> ingested
        "scan": b"%PDF-1.7 corrupt",  # PDF with no readable text -> skipped
        "empty": b"   ",  # whitespace only -> skipped
    }
    sources = [
        _source("doc", storage_key="txt", content_type="text/plain"),
        _source("filing", storage_key="pdf", filename="filing.pdf"),
        _source("scan", storage_key="scan", content_type="application/pdf"),
        _source("blank", storage_key="empty"),
        _source("cite", storage_key=None),  # URL-only citation -> skipped
    ]
    docs = _documents(sources, _Storage(blobs), fallback_as_of="2026-06-01")
    by_id = {d.source_id: d for d in docs}
    assert set(by_id) == {"doc", "filing"}  # corrupt PDF, blank, URL-only all skipped
    assert by_id["doc"].text == "INTC supplies HPQ."
    assert "TSMC supplies NVDA" in by_id["filing"].text
    assert by_id["doc"].as_of == "2026-05-20"  # the source's as_of_date wins over the fallback
