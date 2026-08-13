"""Write model outputs to CSV, JSON, and PNG.

Everything a reader or a downstream loader needs is written here:
inventory, page text, chunks, assignments, summaries, metrics, top terms,
representative chunks, and two visualizations.
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np

from .build_chunks import Chunk
from .discover_ds010 import DocumentAsset
from .evaluate_model import ClusterEvidence
from .extract_pdf import ExtractionResult
from .train_cluster_model import TrainedModel

log = logging.getLogger("export")

# Non-interactive backend so the pipeline runs without a display.
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def write_document_inventory(asset: DocumentAsset, extraction: ExtractionResult,
                             out_dir: Path) -> None:
    path = out_dir / "ds010_document_inventory.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Field", "Value"])
        rows = [
            ("DatasetID", asset.dataset_id),
            ("DatasetName", asset.dataset_name),
            ("SourceOrganization", asset.source_organization),
            ("AssetID", asset.asset_id),
            ("FileName", asset.file_name),
            ("RelativePath", str(asset.relative_path)),
            ("FileFormat", asset.file_format),
            ("AssetType", asset.asset_type),
            ("FileSizeBytes", asset.file_size_bytes),
            ("ExpectedSHA256", asset.expected_sha256),
            ("ChecksumVerified", asset.checksum_verified),
            ("TotalPages", extraction.total_pages),
            ("ExtractedPages", extraction.extracted_pages),
            ("FailedPages", extraction.failed_pages),
            ("TotalWords", extraction.total_words),
        ]
        writer.writerows(rows)
    log.info("Wrote %s", path.name)


def write_page_text(extraction: ExtractionResult, out_dir: Path) -> None:
    path = out_dir / "ds010_page_text.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["PageNumber", "CharCount", "WordCount", "ExtractionOK", "Text"])
        for page in extraction.pages:
            writer.writerow([page.page_number, page.char_count, page.word_count,
                             page.extraction_ok, page.raw_text])
    log.info("Wrote %s (%d pages)", path.name, len(extraction.pages))


def write_chunks(chunks: list[Chunk], out_dir: Path) -> None:
    path = out_dir / "ds010_chunks.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ChunkIndex", "PageNumber", "SectionName", "WordCount",
                         "ChunkChecksum", "ChunkText"])
        for c in chunks:
            writer.writerow([c.chunk_index, c.page_number, c.section_name,
                             c.word_count, c.checksum, c.text])
    log.info("Wrote %s (%d chunks)", path.name, len(chunks))


def write_assignments(model: TrainedModel, chunks: list[Chunk],
                      evidence: list[ClusterEvidence], out_dir: Path) -> None:
    labels = {e.cluster_id: e.suggested_label for e in evidence}
    path = out_dir / "cluster_assignments.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ChunkIndex", "PageNumber", "SectionName", "ClusterID",
                         "ClusterLabel", "DistanceToCentroid", "WordCount", "ChunkText"])
        for i, chunk in enumerate(chunks):
            cid = int(model.labels[i])
            writer.writerow([chunk.chunk_index, chunk.page_number, chunk.section_name,
                             cid, labels.get(cid, ""), round(float(model.distances[i]), 6),
                             chunk.word_count, chunk.text])
    log.info("Wrote %s", path.name)


def write_cluster_summary(evidence: list[ClusterEvidence], out_dir: Path) -> None:
    path = out_dir / "cluster_summary.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ClusterID", "SuggestedLabel", "ChunkCount", "Pages",
                         "MeanDistanceToCentroid", "TopTerms", "HumanReviewed"])
        for e in evidence:
            writer.writerow([
                e.cluster_id, e.suggested_label, e.size,
                ";".join(str(p) for p in e.pages), e.mean_distance,
                ";".join(t for t, _ in e.top_terms), "FALSE",
            ])
    log.info("Wrote %s", path.name)


def write_top_terms(evidence: list[ClusterEvidence], out_dir: Path) -> None:
    path = out_dir / "top_terms_by_cluster.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ClusterID", "Rank", "Term", "CentroidWeight"])
        for e in evidence:
            for rank, (term, weight) in enumerate(e.top_terms, start=1):
                writer.writerow([e.cluster_id, rank, term, round(weight, 6)])
    log.info("Wrote %s", path.name)


def write_representative_chunks(evidence: list[ClusterEvidence], out_dir: Path) -> None:
    path = out_dir / "representative_chunks.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ClusterID", "Rank", "ChunkIndex", "PageNumber",
                         "SectionName", "Distance", "ChunkText"])
        for e in evidence:
            for rank, rep in enumerate(e.representative_chunks, start=1):
                writer.writerow([e.cluster_id, rank, rep["chunk_index"], rep["page_number"],
                                 rep["section_name"], rep["distance"], rep["text"]])
    log.info("Wrote %s", path.name)


def write_metrics(model: TrainedModel, extraction: ExtractionResult,
                  chunks: list[Chunk], evidence: list[ClusterEvidence],
                  asset: DocumentAsset, config: dict,
                  started: datetime, out_dir: Path) -> dict:
    chosen = next((c for c in model.candidates if c.k == model.selected_k), None)
    metrics = {
        "model_name": config["model"]["name"],
        "model_version": config["model"]["version"],
        "algorithm": config["model"]["algorithm"],
        "random_seed": config["model"]["random_seed"],
        "dataset_id": asset.dataset_id,
        "checksum_verified": asset.checksum_verified,
        "total_pdf_pages": extraction.total_pages,
        "extracted_pages": extraction.extracted_pages,
        "failed_pages": extraction.failed_pages,
        "total_words": extraction.total_words,
        "n_chunks": len(chunks),
        "chunk_word_min": min((c.word_count for c in chunks), default=0),
        "chunk_word_max": max((c.word_count for c in chunks), default=0),
        "chunk_word_mean": round(sum(c.word_count for c in chunks) / len(chunks), 2) if chunks else 0,
        "vocabulary_size": model.vocabulary_size,
        "candidate_k": [c.k for c in model.candidates],
        "selected_k": model.selected_k,
        "selection_reason": model.selection_reason,
        "silhouette_score": round(chosen.silhouette, 6) if chosen else None,
        "davies_bouldin_score": round(chosen.davies_bouldin, 6) if chosen else None,
        "calinski_harabasz_score": round(chosen.calinski_harabasz, 4) if chosen else None,
        "inertia": round(float(model.kmeans.inertia_), 6),
        "cluster_sizes": [e.size for e in evidence],
        "candidate_scores": [
            {"k": c.k, "silhouette": round(c.silhouette, 6),
             "davies_bouldin": round(c.davies_bouldin, 6),
             "calinski_harabasz": round(c.calinski_harabasz, 4),
             "cluster_sizes": c.cluster_sizes, "min_cluster_size": c.min_cluster_size,
             "eligible": c.eligible, "ineligible_reason": c.ineligible_reason}
            for c in model.candidates
        ],
        "started_at": started.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    path = out_dir / "model_metrics.json"
    path.write_text(json.dumps(metrics, indent=2))
    log.info("Wrote %s", path.name)
    return metrics


def save_model(model: TrainedModel, metrics: dict, config: dict, models_dir: Path) -> None:
    joblib.dump(model.vectorizer, models_dir / "tfidf_vectorizer.joblib")
    joblib.dump(model.kmeans, models_dir / "kmeans_model.joblib")

    import sklearn
    import sys
    metadata = {
        "model_name": config["model"]["name"],
        "model_version": config["model"]["version"],
        "algorithm": config["model"]["algorithm"],
        "random_seed": config["model"]["random_seed"],
        "selected_k": model.selected_k,
        "vocabulary_size": model.vocabulary_size,
        "training_dataset_id": config["input"]["dataset_id"],
        "silhouette_score": metrics.get("silhouette_score"),
        "davies_bouldin_score": metrics.get("davies_bouldin_score"),
        "n_chunks": metrics.get("n_chunks"),
        "trained_at": metrics.get("completed_at"),
        "python_version": sys.version.split()[0],
        "sklearn_version": sklearn.__version__,
        "numpy_version": np.__version__,
        "configuration": config,
        "intended_use": (
            "Exploratory theme discovery over one public health report to support "
            "insurance product research and regional portfolio review."
        ),
        "prohibited_use": [
            "Individual underwriting or eligibility decisions",
            "Premium or rate setting",
            "Customer-level risk scoring",
            "Medical diagnosis or clinical advice",
            "Any use treating regional aggregates as personal health data",
        ],
        "requires_human_review": True,
    }
    (models_dir / "model_metadata.json").write_text(json.dumps(metadata, indent=2))
    log.info("Saved vectorizer, model, and metadata to %s", models_dir)


def write_visualizations(model: TrainedModel, chunks: list[Chunk],
                         evidence: list[ClusterEvidence], config: dict,
                         out_dir: Path) -> None:
    """Two figures: a 2-D cluster scatter and a top-terms bar chart."""
    from sklearn.decomposition import TruncatedSVD

    seed = config["model"]["random_seed"]
    n_comp = config["output"]["svd_components"]

    # --- Figure 1: TruncatedSVD scatter ------------------------------
    svd = TruncatedSVD(n_components=n_comp, random_state=seed)
    coords = svd.fit_transform(model.matrix)
    explained = svd.explained_variance_ratio_.sum()

    fig, ax = plt.subplots(figsize=(10, 7))
    palette = plt.cm.tab10(np.linspace(0, 1, 10))
    for e in evidence:
        mask = model.labels == e.cluster_id
        ax.scatter(coords[mask, 0], coords[mask, 1],
                   s=90, alpha=0.78, color=palette[e.cluster_id % 10],
                   edgecolors="white", linewidths=0.8,
                   label=f"C{e.cluster_id}: {e.suggested_label} (n={e.size})")
    # Annotate each point with its source page for traceability.
    for i, chunk in enumerate(chunks):
        ax.annotate(str(chunk.page_number), (coords[i, 0], coords[i, 1]),
                    fontsize=6, alpha=0.55, ha="center", va="center")

    ax.set_xlabel(f"SVD component 1 ({svd.explained_variance_ratio_[0]:.1%} variance)")
    ax.set_ylabel(f"SVD component 2 ({svd.explained_variance_ratio_[1]:.1%} variance)")
    ax.set_title("DS010 document-theme clusters\n"
                 f"2025 County Health Rankings & Roadmaps Report - K={model.selected_k}, "
                 f"{explained:.1%} variance shown\n"
                 "Point labels are source page numbers", fontsize=11)
    ax.legend(loc="best", fontsize=8, framealpha=0.9)
    ax.grid(alpha=0.25, linestyle="--")
    fig.tight_layout()
    fig.savefig(out_dir / "cluster_visualization.png", dpi=150)
    plt.close(fig)
    log.info("Wrote cluster_visualization.png")

    # --- Figure 2: top terms per cluster -----------------------------
    k = len(evidence)
    ncols = min(3, k)
    nrows = (k + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(5.5 * ncols, 3.6 * nrows), squeeze=False)

    for idx, e in enumerate(evidence):
        ax = axes[idx // ncols][idx % ncols]
        terms = e.top_terms[:8][::-1]
        if not terms:
            ax.axis("off")
            continue
        names = [t for t, _ in terms]
        weights = [w for _, w in terms]
        ax.barh(range(len(names)), weights, color=palette[e.cluster_id % 10], alpha=0.85)
        ax.set_yticks(range(len(names)))
        ax.set_yticklabels(names, fontsize=9)
        ax.set_title(f"Cluster {e.cluster_id} (n={e.size})", fontsize=10)
        ax.set_xlabel("centroid weight", fontsize=8)
        ax.grid(axis="x", alpha=0.25, linestyle="--")

    for idx in range(k, nrows * ncols):
        axes[idx // ncols][idx % ncols].axis("off")

    fig.suptitle("Top TF-IDF terms by cluster - DS010 theme model", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(out_dir / "top_terms_by_cluster.png", dpi=150)
    plt.close(fig)
    log.info("Wrote top_terms_by_cluster.png")
