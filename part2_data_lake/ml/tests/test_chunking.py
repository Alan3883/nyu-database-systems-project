"""Tests for chunk construction."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ml.src import build_chunks, discover_ds010, extract_pdf

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG = yaml.safe_load((ROOT / "ml" / "config.yaml").read_text())


@pytest.fixture(scope="module")
def chunks():
    asset = discover_ds010.discover(ROOT, CONFIG)
    extraction = extract_pdf.extract(ROOT / asset.relative_path, CONFIG)
    return build_chunks.build(extraction, CONFIG)


def test_enough_chunks_to_cluster(chunks):
    """Page-level chunking would give 18 units. Sub-page chunking must
    produce materially more, or clustering is not meaningful."""
    assert len(chunks) > 18, "sub-page chunking did not increase the unit count"
    assert len(chunks) >= 25


def test_no_empty_chunks(chunks):
    for c in chunks:
        assert c.text.strip(), f"chunk {c.chunk_index} is empty"
        assert c.word_count > 0


def test_minimum_word_count_respected(chunks):
    floor = CONFIG["chunking"]["min_words"]
    for c in chunks:
        assert c.word_count >= floor, f"chunk {c.chunk_index} has {c.word_count} words"


def test_page_numbers_preserved(chunks):
    """Every chunk must be traceable to a source page."""
    for c in chunks:
        assert 1 <= c.page_number <= 18


def test_chunks_are_unique(chunks):
    checksums = [c.checksum for c in chunks]
    assert len(checksums) == len(set(checksums)), "duplicate chunks were not removed"


def test_chunk_indices_contiguous(chunks):
    assert [c.chunk_index for c in chunks] == list(range(1, len(chunks) + 1))


def test_checksum_matches_text(chunks):
    import hashlib
    for c in chunks:
        assert c.checksum == hashlib.sha256(c.text.encode("utf-8")).hexdigest()


def test_text_is_not_lost(chunks):
    """Total chunk words should be a large fraction of the extracted words,
    proving chunking does not silently discard content."""
    asset = discover_ds010.discover(ROOT, CONFIG)
    extraction = extract_pdf.extract(ROOT / asset.relative_path, CONFIG)
    chunk_words = sum(c.word_count for c in chunks)
    assert chunk_words >= 0.75 * extraction.total_words, (
        f"chunking kept only {chunk_words} of {extraction.total_words} words")
