"""Split extracted page text into analysis units.

DS010 has 18 pages. Page-level chunks would give 18 units, which is too few
to cluster stably. This module splits within pages on paragraph boundaries,
targeting ~110 words per chunk, and always records the source page so any
finding can be traced back to the document.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass

from .extract_pdf import ExtractionResult

log = logging.getLogger("chunks")


@dataclass
class Chunk:
    chunk_index: int
    page_number: int
    section_name: str
    text: str
    word_count: int
    checksum: str


# A heading is a short line in title case or all caps. Used only to give a
# chunk a human-readable section label, never to alter the text.
_HEADING = re.compile(r"^[A-Z][A-Za-z0-9 ,'&:-]{3,60}$")


def _guess_section(lines: list[str], fallback: str) -> str:
    for line in lines[:3]:
        candidate = line.strip()
        if 4 <= len(candidate) <= 60 and _HEADING.match(candidate):
            return candidate
    return fallback


def _split_paragraphs(text: str) -> list[str]:
    """Split page text into paragraph-like blocks.

    pypdf returns one line per visual line, so blank-line splitting alone is
    unreliable. Sentence-ending punctuation followed by a capitalised line is
    treated as a paragraph boundary.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []

    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        current.append(line)
        ends_sentence = line.endswith((".", "!", "?", ":"))
        if ends_sentence and len(" ".join(current).split()) >= 25:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


def build(extraction: ExtractionResult, config: dict) -> list[Chunk]:
    """Build word-bounded chunks from extracted pages."""
    cfg = config["chunking"]
    target = cfg["target_words"]
    minimum = cfg["min_words"]
    maximum = cfg["max_words"]

    chunks: list[Chunk] = []
    index = 0
    dropped_empty = 0
    dropped_short = 0

    for page in extraction.pages:
        if not page.extraction_ok:
            dropped_empty += 1
            continue

        lines = [ln for ln in page.raw_text.splitlines() if ln.strip()]
        section = _guess_section(lines, f"Page {page.page_number}")
        paragraphs = _split_paragraphs(page.raw_text)

        # Accumulate paragraphs until the target size is reached.
        buffer: list[str] = []
        buffer_words = 0

        def flush() -> None:
            nonlocal buffer, buffer_words, index
            if not buffer:
                return
            text = " ".join(buffer).strip()
            words = len(text.split())
            if words >= minimum:
                index += 1
                chunks.append(Chunk(
                    chunk_index=index,
                    page_number=page.page_number,
                    section_name=section,
                    text=text,
                    word_count=words,
                    checksum=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                ))
            buffer = []
            buffer_words = 0

        for para in paragraphs:
            para_words = len(para.split())

            # A single oversized paragraph is split on word count.
            if para_words > maximum:
                flush()
                words = para.split()
                for start in range(0, len(words), target):
                    piece = " ".join(words[start:start + target])
                    if len(piece.split()) >= minimum:
                        index += 1
                        chunks.append(Chunk(
                            chunk_index=index,
                            page_number=page.page_number,
                            section_name=section,
                            text=piece,
                            word_count=len(piece.split()),
                            checksum=hashlib.sha256(piece.encode("utf-8")).hexdigest(),
                        ))
                continue

            buffer.append(para)
            buffer_words += para_words
            if buffer_words >= target:
                flush()

        # Trailing content on the page.
        if buffer:
            if buffer_words < minimum and chunks and chunks[-1].page_number == page.page_number:
                # Merge a short tail into the previous chunk on the same page
                # rather than discarding text.
                prev = chunks[-1]
                merged = f"{prev.text} {' '.join(buffer)}".strip()
                chunks[-1] = Chunk(
                    chunk_index=prev.chunk_index,
                    page_number=prev.page_number,
                    section_name=prev.section_name,
                    text=merged,
                    word_count=len(merged.split()),
                    checksum=hashlib.sha256(merged.encode("utf-8")).hexdigest(),
                )
                buffer, buffer_words = [], 0
            else:
                if buffer_words < minimum:
                    dropped_short += 1
                flush()

    # Deduplicate by checksum. Repeated boilerplate would otherwise pull
    # clusters toward itself.
    seen: set[str] = set()
    unique: list[Chunk] = []
    duplicates = 0
    for chunk in chunks:
        if chunk.checksum in seen:
            duplicates += 1
            continue
        seen.add(chunk.checksum)
        unique.append(chunk)

    # Renumber after deduplication so indices stay contiguous.
    for position, chunk in enumerate(unique, start=1):
        chunk.chunk_index = position

    log.info("Built %d chunks from %d pages (skipped %d text-free pages, "
             "%d short fragments, %d duplicates)",
             len(unique), extraction.extracted_pages, dropped_empty, dropped_short, duplicates)
    if unique:
        sizes = [c.word_count for c in unique]
        log.info("Chunk words: min=%d max=%d mean=%.1f",
                 min(sizes), max(sizes), sum(sizes) / len(sizes))
    return unique
