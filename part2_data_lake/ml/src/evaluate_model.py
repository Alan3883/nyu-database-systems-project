"""Derive interpretable evidence from the trained model.

Produces the three things a human reviewer needs to judge a cluster:
  - the terms that define it,
  - the chunks closest to its centre,
  - and its size.

Cluster labels are generated from top terms as a starting point only. The
governance rule is that a label is a hypothesis until a person reviews it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from .build_chunks import Chunk
from .train_cluster_model import TrainedModel

log = logging.getLogger("evaluate")


@dataclass
class ClusterEvidence:
    cluster_id: int
    size: int
    top_terms: list[tuple[str, float]]
    representative_chunks: list[dict]
    pages: list[int]
    mean_distance: float
    suggested_label: str


def top_terms_for_cluster(model: TrainedModel, cluster_id: int, n: int) -> list[tuple[str, float]]:
    """Return the highest-weighted terms at a cluster centroid."""
    features = np.array(model.vectorizer.get_feature_names_out())
    centroid = model.kmeans.cluster_centers_[cluster_id]
    order = centroid.argsort()[::-1][:n]
    return [(str(features[i]), float(centroid[i])) for i in order if centroid[i] > 0]


def representative_chunks(model: TrainedModel, chunks: list[Chunk],
                          cluster_id: int, n: int) -> list[dict]:
    """Return the n chunks closest to the cluster centroid."""
    member_idx = np.where(model.labels == cluster_id)[0]
    if member_idx.size == 0:
        return []
    ordered = member_idx[np.argsort(model.distances[member_idx])][:n]
    out = []
    for i in ordered:
        chunk = chunks[i]
        out.append({
            "chunk_index": chunk.chunk_index,
            "page_number": chunk.page_number,
            "section_name": chunk.section_name,
            "distance": round(float(model.distances[i]), 6),
            "text": chunk.text,
        })
    return out


def _suggest_label(top_terms: list[tuple[str, float]]) -> str:
    """Build a provisional label from the leading terms.

    This is a naming convenience, not an interpretation. Human review
    replaces it in ML_CLUSTER_SUMMARY.
    """
    words = [t for t, _ in top_terms[:3]]
    return " / ".join(w.title() for w in words) if words else "Unlabeled"


def evaluate(model: TrainedModel, chunks: list[Chunk], config: dict) -> list[ClusterEvidence]:
    """Build evidence for every cluster."""
    out_cfg = config["output"]
    evidence: list[ClusterEvidence] = []

    for cid in range(model.selected_k):
        member_idx = np.where(model.labels == cid)[0]
        terms = top_terms_for_cluster(model, cid, out_cfg["top_terms_per_cluster"])
        reps = representative_chunks(model, chunks, cid,
                                     out_cfg["representative_chunks_per_cluster"])
        pages = sorted({chunks[i].page_number for i in member_idx})
        mean_dist = float(model.distances[member_idx].mean()) if member_idx.size else 0.0

        evidence.append(ClusterEvidence(
            cluster_id=cid,
            size=int(member_idx.size),
            top_terms=terms,
            representative_chunks=reps,
            pages=pages,
            mean_distance=round(mean_dist, 6),
            suggested_label=_suggest_label(terms),
        ))
        log.info("Cluster %d: %d chunks, pages %s, label %r",
                 cid, member_idx.size, pages, evidence[-1].suggested_label)

    return evidence
