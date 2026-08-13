"""Load ML pipeline outputs into the PostgreSQL ML governance tables.

Populates ML_RUN, DOCUMENT_CHUNK, ML_CLUSTER_RESULT, and ML_CLUSTER_SUMMARY
so model results are queryable alongside the insurance and hybrid data.

Usage:
    python3 scripts/load_ml_results_to_postgres.py
"""

from __future__ import annotations

import csv
import json
import logging
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "ml" / "outputs"
CONTAINER = "part2-postgres"
DB = "part3"

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("load-ml")


def psql(sql: str, capture: bool = False) -> str:
    result = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "psql", "-U", "postgres", "-d", DB,
         "-v", "ON_ERROR_STOP=1", "-At" if capture else "-q", "-c", sql],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"psql failed: {result.stderr.strip()}")
    return result.stdout.strip()


def sql_str(value: str) -> str:
    """Quote a Python string as a SQL literal."""
    return "'" + str(value).replace("'", "''") + "'"


def main() -> int:
    metrics = json.loads((OUT / "model_metrics.json").read_text())

    log.info("Clearing previous ML run data")
    psql("TRUNCATE ML_CLUSTER_SUMMARY, ML_CLUSTER_RESULT, DOCUMENT_CHUNK, ML_RUN "
         "RESTART IDENTITY CASCADE;")

    # --- ML_RUN ------------------------------------------------------
    config = json.loads(json.dumps(
        json.loads((ROOT / "ml" / "models" / "model_metadata.json").read_text())["configuration"]))
    run_id = psql(f"""
        INSERT INTO ML_RUN (ModelName, ModelVersion, Algorithm, ConfigurationJSON,
                            RandomSeed, TrainingDatasetID, StartedAt, CompletedAt,
                            Status, MetricsJSON)
        VALUES ({sql_str(metrics['model_name'])},
                {sql_str(metrics['model_version'])},
                {sql_str(metrics['algorithm'])},
                {sql_str(json.dumps(config))}::jsonb,
                {metrics['random_seed']},
                {sql_str(metrics['dataset_id'])},
                {sql_str(metrics['started_at'])}::timestamptz,
                {sql_str(metrics['completed_at'])}::timestamptz,
                'Completed',
                {sql_str(json.dumps(metrics))}::jsonb)
        RETURNING MLRunID;
    """, capture=True)
    run_id = int(run_id.splitlines()[0])
    log.info("Created ML_RUN %d", run_id)

    # --- DOCUMENT_CHUNK ----------------------------------------------
    # DataAssetID must reference the real DS010 asset row.
    asset_id = psql("SELECT AssetID FROM DATA_ASSET WHERE DatasetID='DS010' "
                    "AND AssetType='unstructured document' LIMIT 1;", capture=True)
    if not asset_id:
        log.error("No DS010 asset row in DATA_ASSET; load curated data first.")
        return 1
    asset_id = int(asset_id.splitlines()[0])

    chunk_id_by_index: dict[int, int] = {}
    with (OUT / "ds010_chunks.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    values = []
    for r in rows:
        values.append(
            f"({asset_id}, {r['PageNumber']}, {sql_str(r['SectionName'])}, "
            f"{sql_str(r['ChunkText'])}, {r['WordCount']}, {sql_str(r['ChunkChecksum'])})")
    out = psql(
        "INSERT INTO DOCUMENT_CHUNK (DataAssetID, PageNumber, SectionName, ChunkText, "
        "WordCount, ChunkChecksum) VALUES " + ",".join(values) +
        " RETURNING DocumentChunkID;", capture=True)
    ids = [int(x) for x in out.splitlines() if x.strip().isdigit()]
    for r, cid in zip(rows, ids):
        chunk_id_by_index[int(r["ChunkIndex"])] = cid
    log.info("Loaded %d document chunks", len(ids))

    # --- ML_CLUSTER_RESULT -------------------------------------------
    with (OUT / "cluster_assignments.csv").open(encoding="utf-8") as handle:
        assignments = list(csv.DictReader(handle))

    max_dist = max(float(a["DistanceToCentroid"]) for a in assignments) or 1.0
    values = []
    for a in assignments:
        cid = chunk_id_by_index[int(a["ChunkIndex"])]
        dist = float(a["DistanceToCentroid"])
        # RelativeScore: 1.0 = at the centroid, 0.0 = furthest chunk in the run.
        rel = round(1.0 - (dist / max_dist), 6)
        values.append(f"({run_id}, {cid}, {a['ClusterID']}, {dist:.6f}, {rel})")
    psql("INSERT INTO ML_CLUSTER_RESULT (MLRunID, DocumentChunkID, ClusterID, "
         "DistanceToCentroid, RelativeScore) VALUES " + ",".join(values) + ";")
    log.info("Loaded %d cluster results", len(values))

    # --- ML_CLUSTER_SUMMARY ------------------------------------------
    top_terms: dict[int, list[str]] = {}
    with (OUT / "top_terms_by_cluster.csv").open(encoding="utf-8") as handle:
        for r in csv.DictReader(handle):
            top_terms.setdefault(int(r["ClusterID"]), []).append(r["Term"])

    reps: dict[int, list[dict]] = {}
    with (OUT / "representative_chunks.csv").open(encoding="utf-8") as handle:
        for r in csv.DictReader(handle):
            reps.setdefault(int(r["ClusterID"]), []).append({
                "chunk_index": int(r["ChunkIndex"]),
                "page": int(r["PageNumber"]),
                "distance": float(r["Distance"]),
            })

    values = []
    with (OUT / "cluster_summary.csv").open(encoding="utf-8") as handle:
        for r in csv.DictReader(handle):
            cid = int(r["ClusterID"])
            # HumanReviewed is FALSE on load. Review is a separate, explicit
            # action recorded with a reviewer and a timestamp.
            values.append(
                f"({run_id}, {cid}, {sql_str(r['SuggestedLabel'])}, "
                f"{sql_str(json.dumps(top_terms.get(cid, [])))}::jsonb, "
                f"{sql_str(json.dumps(reps.get(cid, [])))}::jsonb, "
                f"NULL, FALSE, NULL, NULL)")
    psql("INSERT INTO ML_CLUSTER_SUMMARY (MLRunID, ClusterID, ClusterLabel, TopTermsJSON, "
         "RepresentativeChunksJSON, BusinessInterpretation, HumanReviewed, ReviewedAt, "
         "ReviewedBy) VALUES " + ",".join(values) + ";")
    log.info("Loaded %d cluster summaries", len(values))

    psql("ANALYZE ML_RUN, DOCUMENT_CHUNK, ML_CLUSTER_RESULT, ML_CLUSTER_SUMMARY;")

    for table in ["ML_RUN", "DOCUMENT_CHUNK", "ML_CLUSTER_RESULT", "ML_CLUSTER_SUMMARY"]:
        n = psql(f"SELECT count(*) FROM {table};", capture=True)
        log.info("  %-20s %s rows", table, n)

    log.info("ML results loaded into PostgreSQL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
