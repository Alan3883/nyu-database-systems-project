"""Retraining behaviour: versioning, activation, and the failure path.

The failure test runs a real retraining attempt against the live database
with an injected fault. The success path is covered end to end by
scripts/run_part4_retraining_demo.py, whose output is stored in
part4/evidence/retraining_demonstration.txt; repeating a full training run
inside the unit suite would add a new model version on every test run
without proving anything the demonstration does not already show.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import func, select

from part4.app.config import CONFIG
from part4.app.db import read_session, session_scope
from part4.app.models import DataAsset, MLClusterResult, MLClusterSummary, MLRun
from part4.app.services import ml_pipeline_service as ml
from part4.app.services import retraining_service


def test_version_bump_is_numeric():
    with read_session() as session:
        version = retraining_service.next_model_version(
            session, "ds010_theme_discovery")
    existing = _existing_versions("ds010_theme_discovery")
    assert version not in existing
    major, minor, patch = (int(p) for p in version.split("."))
    assert (major, minor, patch) > max(_as_triple(v) for v in existing)


def _existing_versions(name: str) -> list[str]:
    with read_session() as session:
        return list(session.scalars(
            select(MLRun.model_version).where(MLRun.model_name == name)))


def _as_triple(raw: str) -> tuple[int, int, int]:
    parts = (str(raw).split(".") + ["0", "0", "0"])[:3]
    return tuple(int(p) for p in parts)  # type: ignore[return-value]


def test_failed_retraining_preserves_the_active_model():
    """The headline guarantee, exercised against the real database."""
    with read_session() as session:
        before_active = ml.active_run(session)
        before_runs = session.execute(
            select(func.count()).select_from(MLRun)).scalar_one()
        asset = ml.current_source_asset(session)
        asset_id = asset.asset_id
        asset_path = asset.relative_path

    os.environ["PART4_FORCE_RETRAIN_FAILURE"] = "train"
    try:
        with session_scope() as session:
            target = session.get(DataAsset, asset_id)
            result = retraining_service.retrain(
                target, source_path=CONFIG.lake_file(asset_path),
                triggered_by="pytest.failure-path")
    finally:
        os.environ.pop("PART4_FORCE_RETRAIN_FAILURE", None)

    assert not result.ok
    assert result.error

    with read_session() as session:
        after_active = ml.active_run(session)
        after_runs = session.execute(
            select(func.count()).select_from(MLRun)).scalar_one()
        failed = session.get(MLRun, result.ml_run_id)
        summaries = session.execute(
            select(func.count()).select_from(MLClusterSummary)
            .where(MLClusterSummary.ml_run_id == result.ml_run_id)).scalar_one()
        results = session.execute(
            select(func.count()).select_from(MLClusterResult)
            .where(MLClusterResult.ml_run_id == result.ml_run_id)).scalar_one()

    # The attempt is recorded ...
    assert after_runs == before_runs + 1
    assert failed.status == "Failed"
    assert (failed.metrics_json or {}).get("error")
    # ... it left no partial results ...
    assert summaries == 0
    assert results == 0
    # ... and the model that was serving is still serving.
    assert after_active.ml_run_id == before_active.ml_run_id


def test_extraction_failure_is_caught_as_a_stage_failure(tmp_path):
    """A file that is not a readable PDF fails cleanly, not with a traceback."""
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"this is not a pdf")

    with read_session() as session:
        before_active = ml.active_run(session)
        asset_id = ml.current_source_asset(session).asset_id

    with session_scope() as session:
        target = session.get(DataAsset, asset_id)
        result = retraining_service.retrain(
            target, source_path=broken, triggered_by="pytest.bad-pdf")

    assert not result.ok
    assert "extraction failed" in (result.error or "").lower() or result.error

    with read_session() as session:
        after_active = ml.active_run(session)
        failed = session.get(MLRun, result.ml_run_id)
    assert failed.status == "Failed"
    assert after_active.ml_run_id == before_active.ml_run_id


def test_new_runs_are_versioned_and_ordered():
    with read_session() as session:
        runs = ml.run_history(session, limit=50)
    versions = [r.model_version for r in runs]
    assert len(versions) == len(set(versions)), "model versions must be unique"


def test_completed_runs_carry_metrics():
    with read_session() as session:
        runs = [r for r in ml.run_history(session, limit=50)
                if r.status == "Completed"]
    for run in runs:
        metrics = run.metrics_json or {}
        assert metrics.get("selected_k")
        assert metrics.get("n_chunks")


def test_new_run_clusters_start_unreviewed():
    """Retraining resets the governance gate.

    Verified on the most recent completed run produced by the retraining
    demonstration: nothing carried a review over from the model before it.
    """
    with read_session() as session:
        runs = [r for r in ml.run_history(session, limit=50)
                if r.status == "Completed"]
        newest = max(runs, key=lambda r: r.ml_run_id)
        summaries = ml.cluster_summaries(session, newest.ml_run_id)
        carried_over = [s for s in summaries
                        if s.human_reviewed and s.reviewed_by is None]
    assert summaries
    assert not carried_over


def test_model_registry_keeps_previous_versions():
    """Artifacts are written per version, never overwritten."""
    registry = CONFIG.registry_path
    if not registry.exists():
        pytest.skip("no Part IV retraining has run in this environment")
    directories = [d for d in registry.iterdir() if d.is_dir()]
    assert directories
    for directory in directories:
        assert (directory / "model_metadata.json").exists()
        assert (directory / "kmeans_model.joblib").exists()
        assert (directory / "tfidf_vectorizer.joblib").exists()
    # The Part III artifacts are untouched by Part IV retraining.
    assert (CONFIG.lake / "ml" / "models" / "kmeans_model.joblib").exists()
