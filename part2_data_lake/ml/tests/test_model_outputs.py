"""Tests that the exported model outputs are complete and internally consistent."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "ml" / "outputs"
MODELS = ROOT / "ml" / "models"
CONFIG = yaml.safe_load((ROOT / "ml" / "config.yaml").read_text())

EXPECTED_OUTPUTS = [
    "ds010_document_inventory.csv",
    "ds010_page_text.csv",
    "ds010_chunks.csv",
    "cluster_assignments.csv",
    "cluster_summary.csv",
    "model_metrics.json",
    "top_terms_by_cluster.csv",
    "representative_chunks.csv",
    "cluster_visualization.png",
    "top_terms_by_cluster.png",
]


@pytest.fixture(scope="module")
def metrics():
    return json.loads((OUT / "model_metrics.json").read_text())


@pytest.mark.parametrize("name", EXPECTED_OUTPUTS)
def test_output_exists_and_is_not_empty(name):
    path = OUT / name
    assert path.exists(), f"missing output {name}"
    assert path.stat().st_size > 0, f"empty output {name}"


def test_model_artifacts_saved():
    for name in ["tfidf_vectorizer.joblib", "kmeans_model.joblib", "model_metadata.json"]:
        assert (MODELS / name).exists(), f"missing model artifact {name}"


def test_metrics_are_real_numbers(metrics):
    assert metrics["n_chunks"] > 0
    assert metrics["vocabulary_size"] > 0
    assert metrics["selected_k"] >= 2
    assert metrics["silhouette_score"] is not None
    assert -1.0 <= metrics["silhouette_score"] <= 1.0
    assert metrics["davies_bouldin_score"] > 0


def test_selected_k_respects_min_cluster_size(metrics):
    """The selected model must not contain a cluster below the configured floor."""
    floor = CONFIG["clustering"]["min_cluster_size"]
    assert min(metrics["cluster_sizes"]) >= floor
    assert len(metrics["cluster_sizes"]) == metrics["selected_k"]


def test_cluster_sizes_sum_to_chunk_count(metrics):
    assert sum(metrics["cluster_sizes"]) == metrics["n_chunks"]


def test_every_chunk_assigned_exactly_once(metrics):
    with (OUT / "cluster_assignments.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == metrics["n_chunks"]
    indices = [int(r["ChunkIndex"]) for r in rows]
    assert len(set(indices)) == len(indices), "a chunk appears more than once"


def test_assignments_reference_valid_clusters(metrics):
    with (OUT / "cluster_assignments.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    valid = set(range(metrics["selected_k"]))
    for r in rows:
        assert int(r["ClusterID"]) in valid


def test_every_cluster_has_top_terms(metrics):
    with (OUT / "top_terms_by_cluster.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    seen = {int(r["ClusterID"]) for r in rows}
    assert seen == set(range(metrics["selected_k"]))


def test_every_cluster_has_representative_chunks(metrics):
    with (OUT / "representative_chunks.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    seen = {int(r["ClusterID"]) for r in rows}
    assert seen == set(range(metrics["selected_k"]))


def test_model_metadata_declares_prohibited_uses():
    """Model governance: the metadata must carry the prohibited-use list."""
    meta = json.loads((MODELS / "model_metadata.json").read_text())
    assert meta["requires_human_review"] is True
    prohibited = " ".join(meta["prohibited_use"]).lower()
    for term in ["underwriting", "premium", "risk scoring", "diagnosis"]:
        assert term in prohibited, f"prohibited-use list does not mention {term}"


def test_summary_marks_clusters_unreviewed():
    """Freshly exported clusters must not claim human review."""
    with (OUT / "cluster_summary.csv").open() as handle:
        for row in csv.DictReader(handle):
            assert row["HumanReviewed"].upper() == "FALSE"
