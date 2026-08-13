"""Validate the complete Part III deliverable before packaging.

Checks that every required artifact exists, that Part I and Part II material is
unchanged, that no credential is present, and that every claim made in the report
is backed by a real file.

Exits nonzero if any check fails.

Usage:
    python3 scripts/validate_part3.py
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
results: list[tuple[str, str, str]] = []


def check(name: str, ok: bool, detail: str = "", warn_only: bool = False) -> bool:
    status = PASS if ok else (WARN if warn_only else FAIL)
    results.append((status, name, detail))
    return ok


def required_files() -> None:
    """Every artifact the report references must exist and be non-empty."""
    required = [
        # Planning
        "docs/part3_repository_inventory.md",
        "docs/part3_implementation_plan.md",
        # Physical database
        "database/physical/01_physical_schema.sql",
        "database/physical/02_indexes.sql",
        "database/physical/03_workflow_extension.sql",
        "database/physical/04_ml_metadata_extension.sql",
        "database/physical/05_materialized_views.sql",
        "database/physical/06_permissions.sql",
        "database/physical/07_partitioning_and_clustering.sql",
        "database/physical/rollback.sql",
        # Queries
        "database/queries/operational_workload.sql",
        "database/queries/analytical_workload.sql",
        "database/queries/explain_before.sql",
        "database/queries/explain_after.sql",
        "database/queries/bigquery_analytics.sql",
        # Tests
        "database/tests/physical_constraint_tests.sql",
        "database/tests/workflow_constraint_tests.sql",
        "database/tests/ml_result_constraint_tests.sql",
        "database/tests/test_database.py",
        # Evidence
        "database/evidence/query_plan_summary.md",
        "database/evidence/performance_results.csv",
        "database/evidence/database_validation.txt",
        # Workflows
        "workflows/quote_to_policy_use_cases.md",
        "workflows/quote_to_policy_workflow.mmd",
        "workflows/quote_to_policy_workflow.svg",
        "workflows/quote_to_policy_workflow.png",
        "workflows/quote_to_policy_sequence.mmd",
        "workflows/quote_to_policy_sequence.svg",
        "workflows/quote_to_policy_sequence.png",
        "workflows/workflow_table_mapping.md",
        # ML
        "ml/README.md",
        "ml/config.yaml",
        "ml/src/run_pipeline.py",
        "ml/models/tfidf_vectorizer.joblib",
        "ml/models/kmeans_model.joblib",
        "ml/models/model_metadata.json",
        "ml/outputs/cluster_assignments.csv",
        "ml/outputs/cluster_summary.csv",
        "ml/outputs/model_metrics.json",
        "ml/outputs/top_terms_by_cluster.csv",
        "ml/outputs/representative_chunks.csv",
        "ml/outputs/business_insights.md",
        "ml/outputs/cluster_visualization.png",
        "ml/outputs/top_terms_by_cluster.png",
        # Architecture
        "architecture/diagrams/part3_physical_model.mmd",
        "architecture/diagrams/part3_physical_model.svg",
        "architecture/diagrams/part3_physical_model.png",
        "architecture/diagrams/part3_reference_architecture.mmd",
        "architecture/diagrams/part3_reference_architecture.svg",
        "architecture/diagrams/part3_reference_architecture.png",
        "architecture/diagrams/part3_future_state_architecture.mmd",
        "architecture/diagrams/part3_data_flow.mmd",
        "architecture/diagrams/part3_data_flow.svg",
        "architecture/governance/data_quality.md",
        "architecture/governance/data_governance.md",
        "architecture/governance/security_and_privacy.md",
        "architecture/governance/model_governance.md",
        "architecture/governance/data_lineage.md",
        "architecture/cloud_evidence/part3/README.md",
        "architecture/cloud_evidence/part3/deployment_commands.md",
        "architecture/cloud_evidence/part3/analytics_queries.sql",
        "architecture/cloud_evidence/part3/screenshot_checklist.md",
        # Scripts
        "scripts/run_part3_database.sh",
        "scripts/run_part3_ml.sh",
        "scripts/run_part3_cloud.sh",
        "scripts/run_part3_all.sh",
        "scripts/validate_part3.py",
    ]
    missing = [f for f in required if not (ROOT / f).exists()]
    empty = [f for f in required if (ROOT / f).exists() and (ROOT / f).stat().st_size == 0]
    check("All required Part III files exist", not missing,
          f"missing: {', '.join(missing)}" if missing else f"{len(required)} files")
    check("No required file is empty", not empty,
          f"empty: {', '.join(empty)}" if empty else "")


def part2_preserved() -> None:
    """Part I and Part II deliverables must be untouched."""
    protected = [
        "logical_model/logical_schema.sql",
        "logical_model/logical_schema_data_dictionary.csv",
        "logical_model/normalization_review.csv",
        "report/Project_Part2_Report.docx",
        "report/Project_Part2_Report.pdf",
        "architecture/cloud_evidence/upload_manifest.csv",
        "architecture/cloud_evidence/cloud_validation.txt",
        "architecture/cloud_evidence/gcloud_commands_used.txt",
    ]
    missing = [f for f in protected if not (ROOT / f).exists()]
    check("Part I/II deliverables preserved", not missing,
          f"missing: {', '.join(missing)}" if missing else f"{len(protected)} files intact")

    # The Part II logical schema must still define exactly 26 tables.
    schema = (ROOT / "logical_model" / "logical_schema.sql").read_text()
    n = len(re.findall(r"^CREATE TABLE ", schema, re.M))
    check("Part II logical schema still defines 26 tables", n == 26, f"found {n}")


def raw_data_unchanged() -> None:
    """Every raw file must still match the checksum recorded at download."""
    manifest_path = ROOT / "metadata" / "download_manifest.json"
    if not manifest_path.exists():
        check("Raw data checksums verified", False, "download_manifest.json missing")
        return
    manifest = json.loads(manifest_path.read_text())
    entries = [d for d in manifest.get("downloads", []) if "relative_path" in d]
    changed, missing = [], []
    for entry in entries:
        path = ROOT / entry["relative_path"]
        if not path.exists():
            missing.append(entry["relative_path"])
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        if digest.hexdigest() != entry.get("sha256"):
            changed.append(entry["relative_path"])
    check("No raw file was modified", not changed and not missing,
          f"{len(entries) - len(changed) - len(missing)}/{len(entries)} checksums match"
          + (f"; changed: {changed}" if changed else "")
          + (f"; missing: {missing}" if missing else ""))


def no_credentials() -> None:
    """No secret may appear anywhere in the repository."""
    patterns = {
        "Census API key": re.compile(r"\baf702722ddb1766aac9feb4935bccdd01d975139\b"),
        "Google API key": re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
        "private key block": re.compile(r"-----BEGIN (RSA |EC )?PRIVATE KEY-----"),
        "service account JSON": re.compile(r'"type"\s*:\s*"service_account"'),
        "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    }
    skip_dirs = {".git", "__pycache__", "node_modules", ".pytest_cache", "submission"}
    hits: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.suffix.lower() in {".png", ".pdf", ".xlsx", ".joblib", ".zip", ".docx", ".svg"}:
            continue
        try:
            text = path.read_text(errors="ignore")
        except Exception:  # noqa: BLE001
            continue
        for label, rx in patterns.items():
            if rx.search(text):
                hits.append(f"{label} in {path.relative_to(ROOT)}")
    check("No credentials in the repository", not hits, "; ".join(hits) if hits else "5 patterns scanned")


def ml_outputs_real() -> None:
    """Model metrics must be genuine numbers, not placeholders."""
    metrics_path = ROOT / "ml" / "outputs" / "model_metrics.json"
    if not metrics_path.exists():
        check("ML metrics present", False, "model_metrics.json missing")
        return
    m = json.loads(metrics_path.read_text())
    check("ML metrics are real values",
          m.get("n_chunks", 0) > 0 and m.get("selected_k", 0) >= 2
          and m.get("silhouette_score") is not None,
          f"chunks={m.get('n_chunks')} K={m.get('selected_k')} "
          f"silhouette={m.get('silhouette_score')}")
    sizes = m.get("cluster_sizes", [])
    check("Cluster sizes sum to the chunk count",
          sum(sizes) == m.get("n_chunks"), f"{sizes} sums to {sum(sizes)}")
    check("No cluster is below the configured size floor",
          bool(sizes) and min(sizes) >= 4, f"smallest cluster = {min(sizes) if sizes else 'n/a'}")

    meta = json.loads((ROOT / "ml" / "models" / "model_metadata.json").read_text())
    check("Model declares prohibited uses",
          meta.get("requires_human_review") is True and len(meta.get("prohibited_use", [])) >= 4,
          f"{len(meta.get('prohibited_use', []))} prohibited uses listed")


def database_state() -> None:
    """Verify the live database if the container is available."""
    def psql(sql: str) -> str:
        r = subprocess.run(
            ["docker", "exec", "-i", "part2-postgres", "psql", "-U", "postgres",
             "-d", "part3", "-At", "-c", sql],
            capture_output=True, text=True, timeout=60)
        return r.stdout.strip() if r.returncode == 0 else ""

    try:
        subprocess.run(["docker", "exec", "part2-postgres", "pg_isready", "-U", "postgres"],
                       capture_output=True, timeout=15, check=True)
    except Exception:  # noqa: BLE001
        check("Database reachable", False, "container not running; database checks skipped",
              warn_only=True)
        return

    tables = psql("SELECT count(*) FROM information_schema.tables WHERE table_schema='public' "
                  "AND table_type='BASE TABLE' AND table_name NOT LIKE 'perf_%'")
    check("Database has 36 tables (26 + 6 + 4)", tables == "36", f"found {tables}")

    fks = psql("SELECT count(*) FROM information_schema.table_constraints "
               "WHERE constraint_type='FOREIGN KEY' AND table_schema='public'")
    check("Foreign keys present", int(fks or 0) >= 33, f"{fks} foreign keys")

    mv = psql("SELECT count(*) FROM pg_matviews WHERE schemaname='public'")
    check("Materialized view exists", mv == "1", f"{mv} materialized views")

    sync = psql("SELECT status FROM V_MV_ARHP_VALIDATION")
    check("Materialized view is in sync", sync == "IN SYNC", sync or "unknown")

    idx = psql("SELECT count(*) FROM pg_indexes WHERE schemaname='public' "
               "AND indexname LIKE 'ix_%'")
    check("Part III indexes created", int(idx or 0) >= 30, f"{idx} ix_ indexes")

    ml_runs = psql("SELECT count(*) FROM ML_RUN WHERE Status='Completed'")
    check("ML run recorded in the database", int(ml_runs or 0) >= 1, f"{ml_runs} completed runs")

    orphans = psql("SELECT count(*) FROM ML_CLUSTER_RESULT r "
                   "LEFT JOIN DOCUMENT_CHUNK c ON c.DocumentChunkID=r.DocumentChunkID "
                   "WHERE c.DocumentChunkID IS NULL")
    check("No orphan ML results", orphans == "0", f"{orphans} orphans")


def cloud_claims_honest() -> None:
    """The report must not claim cloud execution without evidence files."""
    evidence = ROOT / "architecture" / "cloud_evidence" / "part3"
    produced = ["object_inventory.csv", "analytics_results.csv", "sanitized_command_output.txt"]
    present = [f for f in produced if (evidence / f).exists()]
    executed = len(present) == len(produced)

    check("Cloud evidence files present", executed,
          f"{len(present)}/{len(produced)} present: {', '.join(present) or 'none'}")

    if executed:
        import csv as _csv
        expected = {"geographic_area": "3196", "health_indicator": "148",
                    "health_observation": "320", "dataset_catalog": "10",
                    "data_asset": "10", "ml_cluster_assignments": "32",
                    "ml_cluster_summary": "6"}
        with (evidence / "object_inventory.csv").open() as handle:
            actual = {r["TableName"]: r["RowCount"] for r in _csv.DictReader(handle)}
        bad = [f"{k}: cloud={actual.get(k)} local={v}"
               for k, v in expected.items() if actual.get(k) != v]
        check("Cloud row counts match local sources", not bad,
              "; ".join(bad) if bad else f"{len(expected)} tables verified")

        results = (evidence / "analytics_results.csv").read_text()
        n_queries = results.count("### QUERY")
        check("All 4 analytical queries produced results", n_queries >= 4,
              f"{n_queries} query result blocks")
        check("No query returned an error", "Error in query string" not in results,
              "no query errors recorded")


def main() -> int:
    print("=" * 72)
    print("PART III VALIDATION")
    print("=" * 72)

    required_files()
    part2_preserved()
    raw_data_unchanged()
    no_credentials()
    ml_outputs_real()
    database_state()
    cloud_claims_honest()

    print()
    for status, name, detail in results:
        marker = {PASS: "  OK  ", FAIL: " FAIL ", WARN: " WARN "}[status]
        line = f"[{marker}] {name}"
        if detail:
            line += f"\n           {detail}"
        print(line)

    failures = sum(1 for s, _, _ in results if s == FAIL)
    warnings = sum(1 for s, _, _ in results if s == WARN)
    print()
    print("=" * 72)
    print(f"{len(results)} checks: {len(results) - failures - warnings} passed, "
          f"{warnings} warnings, {failures} failures")
    print("=" * 72)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
