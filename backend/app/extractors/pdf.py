"""PDF text extraction helper.

pypdf is used because it is pure Python and handles the CJK text in CNINFO
filings correctly. It is slow on 200+ page reports (~30s) but reliable.
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


def extract_text(path: str | Path, *, max_pages: int | None = None) -> str:
    reader = PdfReader(str(path))
    pages = reader.pages if max_pages is None else reader.pages[:max_pages]
    chunks: list[str] = []
    for page in pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - a broken page must not kill the document
            chunks.append("")
    return "\n".join(chunks)


__all__ = ["extract_text"]
