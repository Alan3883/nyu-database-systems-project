"""Tests for DS010 discovery and PDF text extraction."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ml.src import discover_ds010, extract_pdf

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG = yaml.safe_load((ROOT / "ml" / "config.yaml").read_text())


@pytest.fixture(scope="module")
def asset():
    return discover_ds010.discover(ROOT, CONFIG)


@pytest.fixture(scope="module")
def extraction(asset):
    return extract_pdf.extract(ROOT / asset.relative_path, CONFIG)


def test_ds010_resolves_through_metadata(asset):
    """The pipeline must find the PDF via DATASET/DATA_ASSET, not a hard path."""
    assert asset.dataset_id == "DS010"
    assert asset.asset_type == "unstructured document"
    assert asset.file_format.upper() == "PDF"
    assert asset.asset_id > 0, "AssetID should come from the DATA_ASSET table"


def test_source_file_exists(asset):
    assert (ROOT / asset.relative_path).exists()
    assert asset.file_size_bytes > 1_000_000


def test_checksum_verified(asset):
    """The recorded checksum must match the file on disk."""
    assert asset.expected_sha256, "No checksum on record for DS010"
    assert asset.checksum_verified, "DS010 checksum does not match the manifest"


def test_page_count(extraction):
    assert extraction.total_pages == 18


def test_most_pages_yield_text(extraction):
    """A graphics-heavy report will have some text-free pages, but most
    pages must produce usable prose or the corpus is not analysable."""
    assert extraction.extracted_pages >= 15
    assert extraction.failed_pages <= 3
    assert extraction.extracted_pages + extraction.failed_pages == extraction.total_pages


def test_running_header_removed(extraction):
    """The repeated page header must not survive into the corpus."""
    joined = " ".join(p.raw_text for p in extraction.pages).lower()
    assert "www.countyhealthrankings.org" not in joined


def test_expected_vocabulary_present(extraction):
    """Domain terms the analysis depends on must survive extraction."""
    joined = " ".join(p.raw_text for p in extraction.pages).lower()
    for term in ["health", "community", "housing", "income", "county"]:
        assert term in joined, f"expected domain term missing: {term}"


def test_page_numbers_are_sequential(extraction):
    numbers = [p.page_number for p in extraction.pages]
    assert numbers == list(range(1, extraction.total_pages + 1))
