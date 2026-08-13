"""Orchestrate the DS010 theme-discovery pipeline.

Run with:
    python3 -m ml.src.run_pipeline

Steps:
  1  locate DS010 through data lake metadata and verify its checksum
  2  extract text page by page
  3  build paragraph-aware chunks, preserving page numbers
  4  normalize text
  5  build TF-IDF features
  6  score candidate K values and select one
  7  train the final K-means model
  8  derive top terms and representative chunks
  9  export CSV, JSON, and PNG outputs
 10  save the vectorizer, model, and metadata

Exits nonzero on any failure that invalidates the results.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import build_chunks, discover_ds010, evaluate_model, export_results
from . import extract_pdf, preprocess_text, train_cluster_model

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = ROOT / "ml" / "config.yaml"
LOG_PATH = ROOT / "logs" / "ml_pipeline.log"


def setup_logging() -> logging.Logger:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        handlers=[logging.FileHandler(LOG_PATH, mode="w"), logging.StreamHandler()],
    )
    return logging.getLogger("pipeline")


def main() -> int:
    log = setup_logging()
    started = datetime.now(timezone.utc)
    log.info("=" * 70)
    log.info("Part III ML pipeline - DS010 document theme discovery")
    log.info("=" * 70)

    config = yaml.safe_load(CONFIG_PATH.read_text())
    out_dir = ROOT / config["output"]["outputs_dir"]
    models_dir = ROOT / config["output"]["models_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)

    # --- 1. discover -------------------------------------------------
    log.info("[1/10] Locating DS010 through data lake metadata")
    try:
        asset = discover_ds010.discover(ROOT, config)
    except FileNotFoundError as exc:
        log.error("Cannot locate the source document: %s", exc)
        return 1
    log.info("Resolved %s (%s bytes), checksum verified=%s",
             asset.relative_path, asset.file_size_bytes, asset.checksum_verified)

    # --- 2. extract --------------------------------------------------
    log.info("[2/10] Extracting PDF text")
    extraction = extract_pdf.extract(ROOT / asset.relative_path, config)
    if extraction.extracted_pages == 0:
        log.error("No pages yielded text. Cannot continue.")
        return 1

    # --- 3. chunk ----------------------------------------------------
    log.info("[3/10] Building chunks")
    chunks = build_chunks.build(extraction, config)
    if len(chunks) < 10:
        log.error("Only %d chunks produced; too few to cluster.", len(chunks))
        return 1

    # --- 4. preprocess -----------------------------------------------
    log.info("[4/10] Normalizing text")
    cleaned = preprocess_text.clean_all([c.text for c in chunks], config)

    # --- 5-7. features, selection, training --------------------------
    log.info("[5/10] Building TF-IDF features")
    log.info("[6/10] Scoring candidate K values")
    log.info("[7/10] Training final model")
    try:
        model = train_cluster_model.train(cleaned, config)
    except ValueError as exc:
        log.error("Training failed: %s", exc)
        return 1

    # --- 8. evaluate -------------------------------------------------
    log.info("[8/10] Deriving cluster evidence")
    evidence = evaluate_model.evaluate(model, chunks, config)

    # --- 9. export ---------------------------------------------------
    log.info("[9/10] Exporting outputs")
    export_results.write_document_inventory(asset, extraction, out_dir)
    export_results.write_page_text(extraction, out_dir)
    export_results.write_chunks(chunks, out_dir)
    export_results.write_assignments(model, chunks, evidence, out_dir)
    export_results.write_cluster_summary(evidence, out_dir)
    export_results.write_top_terms(evidence, out_dir)
    export_results.write_representative_chunks(evidence, out_dir)
    metrics = export_results.write_metrics(model, extraction, chunks, evidence,
                                           asset, config, started, out_dir)
    export_results.write_visualizations(model, chunks, evidence, config, out_dir)

    # --- 10. persist model -------------------------------------------
    log.info("[10/10] Saving model artifacts")
    export_results.save_model(model, metrics, config, models_dir)

    log.info("=" * 70)
    log.info("Pipeline complete")
    log.info("  chunks           : %d", metrics["n_chunks"])
    log.info("  vocabulary       : %d", metrics["vocabulary_size"])
    log.info("  selected K       : %d", metrics["selected_k"])
    log.info("  silhouette       : %s", metrics["silhouette_score"])
    log.info("  davies-bouldin   : %s", metrics["davies_bouldin_score"])
    log.info("  cluster sizes    : %s", metrics["cluster_sizes"])
    log.info("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
