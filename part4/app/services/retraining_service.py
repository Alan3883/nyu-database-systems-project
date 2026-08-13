"""Failure-safe retraining of the DS010 theme model.

The Part III pipeline modules do the modelling. This module supplies what
Part IV adds around them: versioning, database registration, governance
reset, and a failure path that cannot damage the running system.

    ml.src.extract_pdf        text extraction
    ml.src.build_chunks       paragraph-aware chunking
    ml.src.preprocess_text    normalisation
    ml.src.train_cluster_model TF-IDF + candidate-K evaluation + K-means
    ml.src.evaluate_model     top terms, representative passages
    ml.src.export_results     model artifact persistence

Activation model
----------------
There is no "active" flag to set. The application defines the active model
as the completed run with the latest CompletedAt, so a run only becomes
active by finishing. The consequences fall out of that single rule:

  * a run that fails is written as Failed and can never be selected;
  * the previously completed run keeps serving with no repair step;
  * partial results cannot appear, because chunks, assignments, and
    summaries are inserted in the same transaction that marks the run
    Completed.

Governance reset
----------------
Every cluster from a new run starts with HumanReviewed = FALSE and no
indicator mapping. Review does not carry over from the previous model:
the clusters are different clusters, and an approval granted for one
model's theme is not an approval of another's.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..config import CONFIG
from ..db import session_scope
from ..models import (
    DataAsset,
    DocumentChunk,
    MLClusterResult,
    MLClusterSummary,
    MLRun,
)

log = logging.getLogger("part4.retrain")

# The repository root must be importable so the Part III ml package can be
# reused rather than copied.
if str(CONFIG.lake) not in sys.path:
    sys.path.insert(0, str(CONFIG.lake))


class RetrainingFailure(RuntimeError):
    """Raised when a stage of the pipeline cannot produce a valid model."""


@dataclass
class RetrainingResult:
    ok: bool
    ml_run_id: int | None
    model_version: str | None
    asset_id: int | None
    asset_version: str | None
    n_chunks: int = 0
    selected_k: int | None = None
    silhouette: float | None = None
    davies_bouldin: float | None = None
    cluster_sizes: list[int] = field(default_factory=list)
    artifact_dir: str | None = None
    message: str = ""
    error: str | None = None


def load_ml_config() -> dict:
    return yaml.safe_load(CONFIG.ml_config_path.read_text())


def next_model_version(session: Session, model_name: str) -> str:
    """Bump the minor version above every version already recorded.

    ML_RUN has UNIQUE(ModelName, ModelVersion), so the new version has to
    be distinct. Versions are compared numerically, not as strings, or
    1.10.0 would sort below 1.9.0.
    """
    versions = list(session.scalars(
        select(MLRun.model_version).where(MLRun.model_name == model_name)))
    best = (0, 0, 0)
    for raw in versions:
        parts = str(raw).split(".")
        try:
            triple = tuple(int(p) for p in (parts + ["0", "0", "0"])[:3])
        except ValueError:
            continue
        best = max(best, triple)
    return f"{best[0] or 1}.{best[1] + 1}.0"


def _maybe_fail(stage: str) -> None:
    """Controlled failure injection for the Test C demonstration.

    Set PART4_FORCE_RETRAIN_FAILURE to a stage name to make that stage
    raise. This exists so the failure path can be demonstrated against the
    real database without corrupting a real source file or model.
    """
    if os.environ.get("PART4_FORCE_RETRAIN_FAILURE", "") == stage:
        raise RetrainingFailure(
            f"Injected failure at stage {stage!r} (PART4_FORCE_RETRAIN_FAILURE).")


# ---------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------
def _run_model_pipeline(source_path: Path, config: dict):
    """Extract, chunk, train, and evaluate. Raises RetrainingFailure."""
    from ml.src import build_chunks, evaluate_model, extract_pdf
    from ml.src import preprocess_text, train_cluster_model

    _maybe_fail("extract")
    try:
        extraction = extract_pdf.extract(source_path, config)
    except Exception as exc:  # noqa: BLE001 - any reader error is a stage failure
        raise RetrainingFailure(f"PDF extraction failed: {exc}") from exc
    if extraction.extracted_pages == 0:
        raise RetrainingFailure("No page yielded text; the source is unusable.")

    chunks = build_chunks.build(extraction, config)
    if len(chunks) < 10:
        raise RetrainingFailure(
            f"Only {len(chunks)} chunks produced; too few to cluster.")

    cleaned = preprocess_text.clean_all([c.text for c in chunks], config)

    _maybe_fail("train")
    try:
        model = train_cluster_model.train(cleaned, config)
    except Exception as exc:  # noqa: BLE001
        raise RetrainingFailure(f"Training failed: {exc}") from exc

    evidence = evaluate_model.evaluate(model, chunks, config)
    if not evidence:
        raise RetrainingFailure("Training produced no clusters.")
    return extraction, chunks, model, evidence


def _persist_artifacts(model, metrics: dict, config: dict, version: str) -> Path:
    """Write the new model to its own registry directory.

    Each version gets a directory of its own, so retraining never
    overwrites the artifacts an earlier run is recorded against. The Part
    III artifacts in ml/models are left untouched.
    """
    from ml.src import export_results

    target = CONFIG.registry_path / f"{config['model']['name']}_{version}"
    target.mkdir(parents=True, exist_ok=True)
    export_results.save_model(model, metrics, config, target)
    return target


# ---------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------
def retrain(asset: DataAsset, *, source_path: Path,
            triggered_by: str = "source-monitor") -> RetrainingResult:
    """Run the full retraining cycle for one source asset version.

    Owns its own transactions rather than joining the caller's, because
    the ML_RUN record must survive a failure of the work that follows it.
    """
    config = load_ml_config()
    model_name = config["model"]["name"]
    started = datetime.now(timezone.utc)

    # --- 1. Register the run before doing any work -------------------
    # Committed on its own. If everything after this throws, the attempt
    # is still on the record instead of vanishing.
    with session_scope() as session:
        version = next_model_version(session, model_name)
        run_config = dict(config)
        run_config["model"] = dict(config["model"], version=version)
        run_config["_part4"] = {
            "triggered_by": triggered_by,
            "source_asset_id": asset.asset_id,
            "source_asset_version": asset.schema_version,
            "source_relative_path": asset.relative_path,
        }
        run = MLRun(
            model_name=model_name,
            model_version=version,
            algorithm=config["model"]["algorithm"],
            configuration_json=run_config,
            random_seed=config["model"]["random_seed"],
            training_dataset_id=asset.dataset_id,
            started_at=started,
            status="Running",
        )
        session.add(run)
        session.flush()
        run_id = run.ml_run_id
        asset_id = asset.asset_id
        asset_version = asset.schema_version
    log.info("Opened ML_RUN %d as version %s", run_id, version)

    # --- 2. Model work, outside any transaction ----------------------
    try:
        extraction, chunks, model, evidence = _run_model_pipeline(source_path, config)
    except Exception as exc:  # noqa: BLE001
        return _mark_failed(run_id, version, asset_id, asset_version, exc,
                            triggered_by)

    # --- 3. Load results and complete the run, atomically ------------
    try:
        with session_scope() as session:
            _maybe_fail("load")
            metrics = _build_metrics(config, version, asset, extraction, chunks,
                                     model, evidence, started)
            artifact_dir = _persist_artifacts(model, metrics, run_config, version)
            metrics["artifact_dir"] = str(artifact_dir.relative_to(CONFIG.part4))

            chunk_ids = _insert_chunks(session, asset_id, chunks)
            _insert_results(session, run_id, chunk_ids, model)
            _insert_summaries(session, run_id, evidence)

            run = session.get(MLRun, run_id)
            run.metrics_json = metrics
            run.completed_at = datetime.now(timezone.utc)
            # Setting Completed is what activates the model. It happens
            # last, in the same transaction as the results.
            run.status = "Completed"
    except Exception as exc:  # noqa: BLE001
        return _mark_failed(run_id, version, asset_id, asset_version, exc,
                            triggered_by)

    result = RetrainingResult(
        ok=True, ml_run_id=run_id, model_version=version,
        asset_id=asset_id, asset_version=asset_version,
        n_chunks=len(chunks), selected_k=model.selected_k,
        silhouette=metrics.get("silhouette_score"),
        davies_bouldin=metrics.get("davies_bouldin_score"),
        cluster_sizes=[e.size for e in evidence],
        artifact_dir=metrics.get("artifact_dir"),
        message=(f"Model {model_name} {version} trained on asset "
                 f"{asset_version} and activated as ML_RUN {run_id}. "
                 f"All {len(evidence)} clusters are unreviewed."),
    )
    log.info(result.message)
    return result


def _mark_failed(run_id: int, version: str, asset_id: int | None,
                 asset_version: str | None, exc: Exception,
                 triggered_by: str = "unknown") -> RetrainingResult:
    """Record the failure and leave the previous model active."""
    message = str(exc).splitlines()[0][:500]
    log.error("Retraining failed for ML_RUN %d: %s", run_id, message)
    try:
        with session_scope() as session:
            run = session.get(MLRun, run_id)
            if run is not None:
                run.status = "Failed"
                run.completed_at = datetime.now(timezone.utc)
                run.metrics_json = {
                    "error": message,
                    "failed_at": datetime.now(timezone.utc).isoformat(),
                    "source_asset_id": asset_id,
                    "source_asset_version": asset_version,
                    # Who asked for this run. Distinguishes a demonstration
                    # or test failure from an operational one in the audit
                    # record.
                    "triggered_by": triggered_by,
                }
    except Exception as inner:  # noqa: BLE001
        log.error("Could not record the failure on ML_RUN %d: %s", run_id, inner)

    return RetrainingResult(
        ok=False, ml_run_id=run_id, model_version=version,
        asset_id=asset_id, asset_version=asset_version,
        message=("Retraining failed. The previously completed model remains "
                 "active and no partial results were stored."),
        error=message,
    )


# ---------------------------------------------------------------------
# Result loading
# ---------------------------------------------------------------------
def _build_metrics(config: dict, version: str, asset: DataAsset, extraction,
                   chunks, model, evidence, started: datetime) -> dict:
    chosen = next((c for c in model.candidates if c.k == model.selected_k), None)
    return {
        "model_name": config["model"]["name"],
        "model_version": version,
        "algorithm": config["model"]["algorithm"],
        "random_seed": config["model"]["random_seed"],
        "dataset_id": asset.dataset_id,
        "source_asset_id": asset.asset_id,
        "source_asset_version": asset.schema_version,
        "source_relative_path": asset.relative_path,
        "source_sha256": asset.sha256,
        "total_pdf_pages": extraction.total_pages,
        "extracted_pages": extraction.extracted_pages,
        "failed_pages": extraction.failed_pages,
        "total_words": extraction.total_words,
        "n_chunks": len(chunks),
        "vocabulary_size": model.vocabulary_size,
        "candidate_k": [c.k for c in model.candidates],
        "selected_k": model.selected_k,
        "selection_reason": model.selection_reason,
        "silhouette_score": round(chosen.silhouette, 6) if chosen else None,
        "davies_bouldin_score": round(chosen.davies_bouldin, 6) if chosen else None,
        "calinski_harabasz_score": round(chosen.calinski_harabasz, 4) if chosen else None,
        "inertia": round(float(model.kmeans.inertia_), 6),
        "cluster_sizes": [e.size for e in evidence],
        "started_at": started.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0],
    }


def _insert_chunks(session: Session, asset_id: int, chunks) -> list[int]:
    """Insert DOCUMENT_CHUNK rows and return their ids by list position.

    The return value is positional, not keyed on Chunk.chunk_index, because
    the model's labels and distances arrays are positional. Keying on
    chunk_index would silently shift every assignment by one: the Part III
    chunker numbers chunks from 1, while the arrays start at 0.

    UNIQUE(DataAssetID, ChunkChecksum) means an identical chunk cannot be
    stored twice against the same asset. A checksum repeated inside one
    extraction reuses the row already inserted for it, so both positions
    still resolve to a chunk id.
    """
    existing = {
        row.chunk_checksum: row.document_chunk_id
        for row in session.scalars(
            select(DocumentChunk).where(DocumentChunk.data_asset_id == asset_id))
    }
    pending: dict[str, DocumentChunk] = {}
    ordered: list[DocumentChunk | int] = []
    added = 0

    for chunk in chunks:
        if chunk.checksum in existing:
            ordered.append(existing[chunk.checksum])
            continue
        row = pending.get(chunk.checksum)
        if row is None:
            row = DocumentChunk(
                data_asset_id=asset_id,
                page_number=chunk.page_number,
                section_name=chunk.section_name,
                chunk_text=chunk.text,
                word_count=chunk.word_count,
                chunk_checksum=chunk.checksum,
            )
            session.add(row)
            pending[chunk.checksum] = row
            added += 1
        ordered.append(row)

    session.flush()
    chunk_ids = [c if isinstance(c, int) else c.document_chunk_id for c in ordered]
    log.info("Stored %d new chunks (%d reused) for asset %d",
             added, len(chunks) - added, asset_id)
    return chunk_ids


def _insert_results(session: Session, run_id: int, chunk_ids: list[int],
                    model) -> None:
    max_distance = float(max(model.distances)) or 1.0
    rows = []
    seen: set[int] = set()
    for index, (label, distance) in enumerate(zip(model.labels, model.distances)):
        if index >= len(chunk_ids):
            continue
        chunk_id = chunk_ids[index]
        # ML_CLUSTER_RESULT is keyed on (MLRunID, DocumentChunkID). Two
        # positions sharing a deduplicated chunk would collide, so the
        # first assignment wins.
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        rows.append({
            "mlrunid": run_id,
            "documentchunkid": chunk_id,
            "clusterid": int(label),
            "distancetocentroid": round(float(distance), 6),
            # 1.0 at the centroid, 0.0 for the furthest chunk in this run.
            "relativescore": round(1.0 - float(distance) / max_distance, 6),
        })
    # Bulk insert: one statement for every assignment instead of one ORM
    # INSERT per chunk.
    session.execute(MLClusterResult.__table__.insert(), rows)
    log.info("Stored %d cluster assignments for run %d", len(rows), run_id)


def _insert_summaries(session: Session, run_id: int, evidence) -> None:
    for item in evidence:
        session.add(MLClusterSummary(
            ml_run_id=run_id,
            cluster_id=item.cluster_id,
            cluster_label=item.suggested_label[:200],
            top_terms_json=[t for t, _ in item.top_terms],
            representative_chunks_json=[
                {"chunk_index": r["chunk_index"], "page": r["page_number"],
                 "distance": r["distance"]}
                for r in item.representative_chunks
            ],
            business_interpretation=None,
            # Governance reset. A new model's themes are unreviewed,
            # whatever was approved for the previous model.
            human_reviewed=False,
            reviewed_at=None,
            reviewed_by=None,
        ))
    session.flush()
    log.info("Stored %d unreviewed cluster summaries for run %d",
             len(evidence), run_id)
