"""Paragraph-aware text chunking with overlap."""

from __future__ import annotations

import re

_PARA = re.compile(r"\n\s*\n")


def chunk_text(text: str, size: int = 1200, overlap: int = 150) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    paras = [p.strip() for p in _PARA.split(text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paras:
        if buf and len(buf) + len(para) + 1 > size:
            chunks.append(buf)
            buf = (buf[-overlap:] + " " + para) if overlap else para
        else:
            buf = f"{buf} {para}".strip() if buf else para
    if buf:
        chunks.append(buf)
    # hard-split any oversized single paragraph
    out: list[str] = []
    for c in chunks:
        if len(c) <= size * 1.5:
            out.append(c)
        else:
            for i in range(0, len(c), size - overlap):
                out.append(c[i : i + size])
    return out
