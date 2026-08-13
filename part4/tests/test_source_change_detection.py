"""SHA-256 change detection over the unstructured source.

These tests are read-only against the watched file. They never write to
the raw zone and never trigger a training run.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from part4.app.config import CONFIG
from part4.app.db import read_session
from part4.app.services import source_monitor_service as monitor
from part4.app.services.errors import NotFound


def test_resolves_ds010_through_the_catalogue():
    """The asset is found through DATASET -> DATA_ASSET, not a hard-coded path."""
    with read_session() as session:
        asset = monitor.resolve_active_asset(session)
    assert asset.dataset_id == "DS010"
    assert asset.asset_type == "unstructured document"
    assert asset.status == "Stored"
    assert len(asset.sha256 or "") == 64


def test_unchanged_source_reports_no_change():
    with read_session() as session:
        asset = monitor.resolve_active_asset(session)
        state = monitor.check_source(session, CONFIG.lake_file(asset.relative_path))
    assert state.source_exists
    assert not state.changed
    assert state.current_sha256 == state.recorded_sha256


def test_changed_content_is_detected(tmp_path: Path):
    """A one-byte difference must register as a change."""
    with read_session() as session:
        asset = monitor.resolve_active_asset(session)
        original = CONFIG.lake_file(asset.relative_path)
        copy = tmp_path / "modified.pdf"
        shutil.copy2(original, copy)
        with copy.open("ab") as handle:
            handle.write(b"\n% part4 change detection test\n")
        state = monitor.check_source(session, copy)
    assert state.changed
    assert state.current_sha256 != state.recorded_sha256


def test_detection_is_not_based_on_modification_time(tmp_path: Path):
    """Touching a file must not look like a content change."""
    with read_session() as session:
        asset = monitor.resolve_active_asset(session)
        original = CONFIG.lake_file(asset.relative_path)
        copy = tmp_path / "touched.pdf"
        shutil.copy2(original, copy)
        # A fresh mtime, identical bytes.
        copy.touch()
        state = monitor.check_source(session, copy)
    assert not state.changed


def test_missing_source_is_reported_not_raised(tmp_path: Path):
    with read_session() as session:
        state = monitor.check_source(session, tmp_path / "absent.pdf")
    assert not state.source_exists
    assert not state.changed
    assert "not found" in state.message.lower()


def test_sha256_matches_hashlib(tmp_path: Path):
    sample = tmp_path / "sample.bin"
    sample.write_bytes(b"part4" * 1000)
    assert monitor.sha256_of(sample) == hashlib.sha256(b"part4" * 1000).hexdigest()


def test_check_is_read_only():
    """Two consecutive checks return the same recorded checksum."""
    with read_session() as session:
        first = monitor.check_source(session)
        second = monitor.check_source(session)
    assert first.recorded_sha256 == second.recorded_sha256
    assert first.asset_id == second.asset_id


def test_every_preserved_version_has_a_distinct_checksum_record():
    """Version history is intact: each row carries its own checksum."""
    from part4.app.services import ml_pipeline_service as ml
    with read_session() as session:
        versions = ml.source_asset_versions(session, limit=20)
    assert versions
    assert all(len(v.sha256 or "") == 64 for v in versions)
    labels = [v.schema_version for v in versions]
    assert len(labels) == len(set(labels)), f"duplicate version labels: {labels}"


def test_only_one_version_is_current():
    from part4.app.services import ml_pipeline_service as ml
    with read_session() as session:
        versions = ml.source_asset_versions(session, limit=20)
    stored = [v for v in versions if v.status == "Stored"]
    assert len(stored) == 1
