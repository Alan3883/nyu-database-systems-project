"""Build TF-IDF features and train the K-means theme model.

Model selection runs every candidate K and scores it with silhouette
(higher is better) and Davies-Bouldin (lower is better). The selected K is
the one with the best silhouette among candidates that produce no singleton
cluster, because a singleton is an artefact rather than a theme.

All randomness is seeded so a rerun reproduces the model exactly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import calinski_harabasz_score, davies_bouldin_score, silhouette_score

log = logging.getLogger("train")


@dataclass
class CandidateScore:
    k: int
    silhouette: float
    davies_bouldin: float
    calinski_harabasz: float
    cluster_sizes: list[int]
    min_cluster_size: int
    eligible: bool
    ineligible_reason: str = ""


@dataclass
class TrainedModel:
    vectorizer: TfidfVectorizer
    kmeans: KMeans
    matrix: object
    labels: np.ndarray
    distances: np.ndarray
    selected_k: int
    vocabulary_size: int
    candidates: list[CandidateScore] = field(default_factory=list)
    selection_reason: str = ""


def build_features(texts: list[str], config: dict) -> tuple[TfidfVectorizer, object]:
    """Fit the TF-IDF vectorizer over the cleaned chunks."""
    cfg = config["features"]
    vectorizer = TfidfVectorizer(
        ngram_range=tuple(cfg["ngram_range"]),
        min_df=cfg["min_df"],
        max_df=cfg["max_df"],
        max_features=cfg["max_features"],
        sublinear_tf=cfg["sublinear_tf"],
        stop_words=cfg["stop_words"],
    )
    matrix = vectorizer.fit_transform(texts)
    log.info("TF-IDF matrix: %d chunks x %d features (density %.3f)",
             matrix.shape[0], matrix.shape[1],
             matrix.nnz / (matrix.shape[0] * matrix.shape[1]))
    return vectorizer, matrix


def evaluate_candidates(matrix, config: dict) -> list[CandidateScore]:
    """Score every candidate K."""
    seed = config["model"]["random_seed"]
    cl = config["clustering"]
    n_samples = matrix.shape[0]
    results: list[CandidateScore] = []

    for k in cl["candidate_k"]:
        # Silhouette needs at least k+1 samples and at least 2 clusters.
        if k >= n_samples:
            log.warning("Skipping k=%d: only %d chunks available", k, n_samples)
            continue

        km = KMeans(n_clusters=k, random_state=seed, n_init=cl["n_init"],
                    max_iter=cl["max_iter"])
        labels = km.fit_predict(matrix)

        sizes = np.bincount(labels, minlength=k).tolist()
        smallest = int(min(sizes))
        min_required = cl.get("min_cluster_size", 2)
        eligible = smallest >= min_required
        reason = "" if eligible else f"smallest cluster {smallest} < {min_required}"

        dense = matrix.toarray()
        sil = float(silhouette_score(matrix, labels, metric="cosine"))
        dbi = float(davies_bouldin_score(dense, labels))
        chi = float(calinski_harabasz_score(dense, labels))

        results.append(CandidateScore(
            k=k, silhouette=sil, davies_bouldin=dbi, calinski_harabasz=chi,
            cluster_sizes=sizes, min_cluster_size=smallest,
            eligible=eligible, ineligible_reason=reason,
        ))
        log.info("k=%d silhouette=%.4f davies_bouldin=%.4f sizes=%s%s",
                 k, sil, dbi, sizes, "" if eligible else f"  [excluded: {reason}]")

    return results


def select_k(candidates: list[CandidateScore], config: dict) -> tuple[int, str]:
    """Choose a defensible K.

    Selection rule, in order:
      1. Disqualify any K whose smallest cluster falls below
         clustering.min_cluster_size. On a 32-chunk corpus the silhouette
         score rises monotonically with K, so an unconstrained argmax
         always picks the largest K and produces two-chunk "themes".
         The size floor is what stops that.
      2. Among eligible K, take the highest silhouette.
      3. Apply a parsimony tie-break: if a smaller eligible K scores within
         parsimony_tolerance of the best, prefer the smaller K. Fewer,
         larger themes are easier for a reviewer to judge.
    """
    cl = config["clustering"]
    forced = cl.get("selected_k")
    if forced:
        return int(forced), f"K={forced} pinned in config.yaml"

    if not candidates:
        raise ValueError("No candidate K values could be evaluated")

    eligible = [c for c in candidates if c.eligible]

    if not eligible:
        best = max(candidates, key=lambda c: c.silhouette)
        reason = (f"No K met the minimum cluster size of {cl.get('min_cluster_size')}. "
                  f"K={best.k} selected on highest silhouette ({best.silhouette:.4f}). "
                  f"Results should be treated as unstable.")
        log.warning(reason)
        return best.k, reason

    best = max(eligible, key=lambda c: c.silhouette)
    tolerance = cl.get("parsimony_tolerance", 0.0)
    simpler = [c for c in eligible
               if c.k < best.k and (best.silhouette - c.silhouette) <= tolerance]

    if simpler:
        chosen = min(simpler, key=lambda c: c.k)
        reason = (f"K={chosen.k} selected. Silhouette {chosen.silhouette:.4f} is within "
                  f"{tolerance:.3f} of the best eligible K={best.k} "
                  f"({best.silhouette:.4f}), so the simpler model is preferred. "
                  f"Davies-Bouldin {chosen.davies_bouldin:.4f}, "
                  f"cluster sizes {chosen.cluster_sizes}.")
    else:
        chosen = best
        excluded = [f"K={c.k} ({c.ineligible_reason})" for c in candidates if not c.eligible]
        reason = (f"K={chosen.k} has the highest silhouette ({chosen.silhouette:.4f}) among "
                  f"candidates whose smallest cluster holds at least "
                  f"{cl.get('min_cluster_size')} chunks; "
                  f"Davies-Bouldin {chosen.davies_bouldin:.4f}, "
                  f"cluster sizes {chosen.cluster_sizes}."
                  + (f" Excluded for fragmentation: {', '.join(excluded)}." if excluded else ""))

    log.info("Selected %s", reason)
    return chosen.k, reason


def train(texts: list[str], config: dict) -> TrainedModel:
    """Full training path: features, model selection, final fit."""
    vectorizer, matrix = build_features(texts, config)
    candidates = evaluate_candidates(matrix, config)
    k, reason = select_k(candidates, config)

    seed = config["model"]["random_seed"]
    cl = config["clustering"]
    kmeans = KMeans(n_clusters=k, random_state=seed, n_init=cl["n_init"],
                    max_iter=cl["max_iter"])
    labels = kmeans.fit_predict(matrix)

    # Distance from each chunk to its assigned centroid. Small distance means
    # the chunk is representative of its cluster.
    all_distances = kmeans.transform(matrix)
    distances = all_distances[np.arange(len(labels)), labels]

    log.info("Final model: k=%d, inertia=%.4f", k, kmeans.inertia_)

    return TrainedModel(
        vectorizer=vectorizer,
        kmeans=kmeans,
        matrix=matrix,
        labels=labels,
        distances=distances,
        selected_k=k,
        vocabulary_size=len(vectorizer.vocabulary_),
        candidates=candidates,
        selection_reason=reason,
    )
