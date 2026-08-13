"""Extract text from the DS010 PDF, one record per page.

Extraction is reported honestly: pages that yield no text are counted as
failures rather than dropped silently, because a graphics-heavy report will
legitimately have pages with no text layer and the report must say so.

No OCR is used. The PDF has a text layer; pages without text are cover art
and section dividers.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader

log = logging.getLogger("extract")


@dataclass
class PageText:
    page_number: int
    raw_text: str
    char_count: int
    word_count: int
    extraction_ok: bool


@dataclass
class ExtractionResult:
    pdf_path: Path
    total_pages: int
    extracted_pages: int
    failed_pages: int
    pages: list[PageText] = field(default_factory=list)

    @property
    def total_words(self) -> int:
        return sum(p.word_count for p in self.pages)


def _strip_running_headers(text: str, patterns: list[str]) -> str:
    """Remove repeated page furniture line by line.

    The report prints a running header on nearly every page. Left in place it
    becomes the highest-weighted term in the corpus and dominates every
    cluster, so it is removed before any feature is built.
    """
    compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(rx.search(stripped) for rx in compiled):
            continue
        kept.append(stripped)
    return "\n".join(kept)


def extract(pdf_path: Path, config: dict) -> ExtractionResult:
    """Read every page of the PDF and return per-page text records."""
    pre = config["preprocessing"]
    patterns = pre["header_patterns"] if pre.get("strip_running_headers", True) else []

    reader = PdfReader(str(pdf_path))
    total = len(reader.pages)
    pages: list[PageText] = []
    failed = 0

    for index, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001 - record and continue
            log.warning("Page %d extraction raised %s", index, exc)
            raw = ""

        cleaned = _strip_running_headers(raw, patterns) if raw else ""
        words = len(cleaned.split())
        # A page counts as extracted only if it yields usable prose.
        ok = words >= 5
        if not ok:
            failed += 1
            log.info("Page %d yielded %d words (no usable text layer)", index, words)

        pages.append(PageText(
            page_number=index,
            raw_text=cleaned,
            char_count=len(cleaned),
            word_count=words,
            extraction_ok=ok,
        ))

    result = ExtractionResult(
        pdf_path=pdf_path,
        total_pages=total,
        extracted_pages=total - failed,
        failed_pages=failed,
        pages=pages,
    )
    log.info("Extracted %d/%d pages (%d without usable text), %d words total",
             result.extracted_pages, total, failed, result.total_words)
    return result
