"""Reproducibility tests.

A fixed seed must produce an identical model. These tests retrain from the
saved configuration and compare against the exported results.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from ml.src import build_chunks, discover_ds010, extract_pdf, preprocess_text, train_cluster_model

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "ml" / "outputs"
CONFIG = yaml.safe_load((ROOT / "ml" / "config.yaml").read_text())


@pytest.fixture(scope="module")
def retrained():
    asset = discover_ds010.discover(ROOT, CONFIG)
    extraction = extract_pdf.extract(ROOT / asset.relative_path, CONFIG)
    chunks = build_chunks.build(extraction, CONFIG)
    cleaned = preprocess_text.clean_all([c.text for c in chunks], CONFIG)
    return train_cluster_model.train(cleaned, CONFIG)


@pytest.fixture(scope="module")
def exported():
    return json.loads((OUT / "model_metrics.json").read_text())


def test_chunk_count_reproduces(retrained, exported):
    assert retrained.matrix.shape[0] == exported["n_chunks"]


def test_vocabulary_reproduces(retrained, exported):
    assert retrained.vocabulary_size == exported["vocabulary_size"]


def test_selected_k_reproduces(retrained, exported):
    assert retrained.selected_k == exported["selected_k"]


def test_cluster_sizes_reproduce(retrained, exported):
    import numpy as np
    sizes = np.bincount(retrained.labels, minlength=retrained.selected_k).tolist()
    assert sorted(sizes) == sorted(exported["cluster_sizes"])


def test_metrics_reproduce(retrained, exported):
    chosen = next(c for c in retrained.candidates if c.k == retrained.selected_k)
    assert round(chosen.silhouette, 6) == exported["silhouette_score"]
    assert round(chosen.davies_bouldin, 6) == exported["davies_bouldin_score"]


def test_inertia_reproduces(retrained, exported):
    assert round(float(retrained.kmeans.inertia_), 6) == exported["inertia"]


def test_seed_is_recorded(exported):
    assert exported["random_seed"] == CONFIG["model"]["random_seed"]


def test_two_fits_agree():
    """Training twice in the same process must give identical labels."""
    asset = discover_ds010.discover(ROOT, CONFIG)
    extraction = extract_pdf.extract(ROOT / asset.relative_path, CONFIG)
    chunks = build_chunks.build(extraction, CONFIG)
    cleaned = preprocess_text.clean_all([c.text for c in chunks], CONFIG)
    a = train_cluster_model.train(cleaned, CONFIG)
    b = train_cluster_model.train(cleaned, CONFIG)
    assert a.selected_k == b.selected_k
    assert list(a.labels) == list(b.labels)
