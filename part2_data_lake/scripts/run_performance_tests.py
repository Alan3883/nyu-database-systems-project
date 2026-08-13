"""Capture EXPLAIN (ANALYZE, BUFFERS) evidence before and after Part III
physical optimization.

The script runs each workload query in the given phase, parses the plan, and
appends a row to database/evidence/performance_results.csv.

Usage:
    python3 scripts/run_performance_tests.py --phase before
    python3 scripts/run_performance_tests.py --phase after
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "database" / "evidence"
CONTAINER = "part2-postgres"
DB = "part3"

# Query id -> (description, SQL). Queries that depend on Part III tables are
# marked so the "before" phase can skip them cleanly.
QUERIES: dict[str, dict] = {
    "Q01": {
        "desc": "Account lookup by business key",
        "table": "ACCOUNT",
        "part3_only": False,
        "sql": """SELECT AccountID, AccountName, AccountType, Status FROM ACCOUNT
                  WHERE AccountName='Demo Account 7' AND Address1='7 Main St'
                    AND City='City7' AND State='AR' AND Zip='70007' AND CompanyCode='DEMO7'""",
    },
    "Q02": {
        "desc": "Customer lookup by surname",
        "table": "CUSTOMER",
        "part3_only": False,
        "sql": "SELECT CustomerID, CustLastName, CustFirstName FROM CUSTOMER WHERE CustLastName='Last42'",
    },
    "Q03": {
        "desc": "Contract lookup by contract number",
        "table": "CONTRACT",
        "part3_only": False,
        "sql": "SELECT ContractID, ContractNumber, AccountID, PlanName FROM CONTRACT WHERE ContractNumber='C-000123'",
    },
    "Q04": {
        "desc": "Account-to-active-contract retrieval",
        "table": "CONTRACT",
        "part3_only": False,
        "sql": """SELECT ContractID, ContractNumber, PlanName, EffectiveDate FROM CONTRACT
                  WHERE AccountID=12 AND Status='Active' ORDER BY EffectiveDate DESC""",
    },
    "Q06": {
        "desc": "Geographic-area-to-account retrieval",
        "table": "ACCOUNT_GEOGRAPHY",
        "part3_only": False,
        "sql": """SELECT ag.AccountID, a.AccountName, ag.RelationshipType FROM ACCOUNT_GEOGRAPHY ag
                  JOIN ACCOUNT a ON a.AccountID=ag.AccountID
                  WHERE ag.GeographyID=1200 AND ag.RelationshipType='PrimaryLocation'""",
    },
    "Q07": {
        "desc": "County FIPS to health indicator retrieval",
        "table": "GEOGRAPHIC_AREA",
        "part3_only": False,
        "sql": """SELECT g.CountyFIPS, g.GeographyName, hi.IndicatorName, ho.MeasureValue
                  FROM GEOGRAPHIC_AREA g
                  JOIN HEALTH_OBSERVATION ho ON ho.GeographyID=g.GeographyID
                  JOIN HEALTH_INDICATOR hi ON hi.IndicatorID=ho.IndicatorID
                  WHERE g.CountyFIPS='05119'""",
    },
    "Q08": {
        "desc": "Account-to-regional-health five-table join",
        "table": "multiple",
        "part3_only": False,
        "sql": """SELECT a.AccountID, a.AccountName, g.CountyFIPS, hi.IndicatorName, ho.MeasureValue
                  FROM ACCOUNT a
                  JOIN ACCOUNT_GEOGRAPHY ag ON ag.AccountID=a.AccountID
                  JOIN GEOGRAPHIC_AREA g ON g.GeographyID=ag.GeographyID
                  JOIN HEALTH_OBSERVATION ho ON ho.GeographyID=g.GeographyID
                  JOIN HEALTH_INDICATOR hi ON hi.IndicatorID=ho.IndicatorID
                  WHERE a.AccountID=12""",
    },
    "Q09": {
        "desc": "Dataset-to-data-asset lineage lookup",
        "table": "DATA_ASSET",
        "part3_only": False,
        "sql": """SELECT d.DatasetID, da.FileName, da.RelativePath, da.SHA256
                  FROM DATASET d JOIN DATA_ASSET da ON da.DatasetID=d.DatasetID
                  WHERE d.DatasetID='DS010' AND da.AssetType='unstructured document'""",
    },
    "Q13": {
        "desc": "Regional indicator aggregation",
        "table": "HEALTH_OBSERVATION",
        "part3_only": False,
        "sql": """SELECT hi.IndicatorName, g.StateCode, count(*) AS n, avg(ho.MeasureValue) AS avg_v
                  FROM HEALTH_OBSERVATION ho
                  JOIN HEALTH_INDICATOR hi ON hi.IndicatorID=ho.IndicatorID
                  JOIN GEOGRAPHIC_AREA g ON g.GeographyID=ho.GeographyID
                  WHERE hi.FactorCategory='Disease outcome'
                  GROUP BY hi.IndicatorName, g.StateCode ORDER BY avg_v DESC LIMIT 25""",
    },
    "Q10": {
        "desc": "Quote open work queue (partial index)",
        "table": "QUOTE",
        "part3_only": True,
        "sql": """SELECT QuoteID, QuoteNumber, QuoteStatus, RequestedDate FROM QUOTE
                  WHERE QuoteStatus IN ('Draft','Submitted','Rated','Presented')
                  ORDER BY RequestedDate DESC LIMIT 50""",
    },
    "Q11": {
        "desc": "Quote-to-contract conversion lookup",
        "table": "QUOTE_CONVERSION",
        "part3_only": True,
        "sql": """SELECT qc.QuoteID, qc.ContractID, qc.ConvertedAt FROM QUOTE_CONVERSION qc
                  WHERE qc.ContractID=301""",
    },
    "Q12": {
        "desc": "ML cluster-result lookup",
        "table": "ML_CLUSTER_RESULT",
        "part3_only": True,
        "sql": """SELECT mcr.ClusterID, mcr.DistanceToCentroid, dc.PageNumber
                  FROM ML_CLUSTER_RESULT mcr
                  JOIN DOCUMENT_CHUNK dc ON dc.DocumentChunkID=mcr.DocumentChunkID
                  WHERE mcr.MLRunID=1 AND mcr.ClusterID=0 ORDER BY mcr.DistanceToCentroid""",
    },
    "Q14": {
        "desc": "Dataset and model-run audit lookup",
        "table": "ML_RUN",
        "part3_only": True,
        "sql": """SELECT r.MLRunID, r.ModelName, r.RandomSeed, r.Status
                  FROM ML_RUN r WHERE r.TrainingDatasetID='DS010' ORDER BY r.StartedAt DESC""",
    },
    "Q16": {
        "desc": "Materialized view read (replaces Q08 join)",
        "table": "MV_ACCOUNT_REGIONAL_HEALTH_PROFILE",
        "part3_only": True,
        "sql": """SELECT AccountID, AccountName, CountyFIPS, IndicatorName, MeasureValue
                  FROM MV_ACCOUNT_REGIONAL_HEALTH_PROFILE WHERE AccountID=12""",
    },
    "Q18": {
        "desc": "Synthetic-scale regional lookup (500k rows)",
        "table": "perf_health_observation_synthetic",
        "part3_only": True,
        "sql": """SELECT GeographyID, IndicatorID, ObservationYear, MeasureValue
                  FROM perf_health_observation_synthetic
                  WHERE GeographyID=1500 AND IndicatorID=20""",
    },
}


def run_explain(sql: str) -> dict | None:
    """Run EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) and return the plan."""
    stmt = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}"
    result = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "psql", "-U", "postgres", "-d", DB,
         "-At", "-c", stmt],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return {"error": result.stderr.strip().splitlines()[0] if result.stderr else "failed"}
    try:
        return json.loads(result.stdout)[0]
    except (json.JSONDecodeError, IndexError):
        return None


def walk_plan(node: dict, found: dict) -> None:
    """Collect scan types, index names, and buffer counts from a plan tree."""
    node_type = node.get("Node Type", "")
    if "Scan" in node_type:
        found["scans"].add(node_type)
    if node.get("Index Name"):
        found["indexes"].add(node["Index Name"])
    found["shared_hit"] += node.get("Shared Hit Blocks", 0) or 0
    found["shared_read"] += node.get("Shared Read Blocks", 0) or 0
    for child in node.get("Plans", []) or []:
        walk_plan(child, found)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["before", "after"], required=True)
    args = parser.parse_args()

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out_file = EVIDENCE / "performance_results.csv"
    plan_file = EVIDENCE / f"explain_{args.phase}_output.txt"

    rows: list[dict] = []
    if args.phase == "after" and out_file.exists():
        with out_file.open() as handle:
            rows = [r for r in csv.DictReader(handle) if r["Phase"] != "after"]

    plan_text: list[str] = []

    for qid, spec in QUERIES.items():
        if args.phase == "before" and spec["part3_only"]:
            continue

        # Row count of the driving table, for context.
        size_out = subprocess.run(
            ["docker", "exec", "-i", CONTAINER, "psql", "-U", "postgres", "-d", DB, "-At",
             "-c", f"SELECT count(*) FROM {spec['table']}"],
            capture_output=True, text=True,
        )
        dataset_size = size_out.stdout.strip() if size_out.returncode == 0 else "n/a"

        plan = run_explain(spec["sql"])
        if plan is None or "error" in (plan or {}):
            err = (plan or {}).get("error", "no plan")
            rows.append({
                "QueryID": qid, "Description": spec["desc"], "DatasetRows": dataset_size,
                "Phase": args.phase, "PlanningTimeMs": "", "ExecutionTimeMs": "",
                "ScanType": "ERROR", "IndexUsed": "", "RowsExamined": "", "RowsReturned": "",
                "SharedHitBlocks": "", "SharedReadBlocks": "", "Notes": err,
            })
            plan_text.append(f"===== {qid} {spec['desc']} =====\nERROR: {err}\n")
            continue

        found = {"scans": set(), "indexes": set(), "shared_hit": 0, "shared_read": 0}
        walk_plan(plan["Plan"], found)

        rows.append({
            "QueryID": qid,
            "Description": spec["desc"],
            "DatasetRows": dataset_size,
            "Phase": args.phase,
            "PlanningTimeMs": round(plan.get("Planning Time", 0), 3),
            "ExecutionTimeMs": round(plan.get("Execution Time", 0), 3),
            "ScanType": "; ".join(sorted(found["scans"])) or "n/a",
            "IndexUsed": "; ".join(sorted(found["indexes"])) or "none",
            "RowsExamined": plan["Plan"].get("Actual Rows", ""),
            "RowsReturned": plan["Plan"].get("Actual Rows", ""),
            "SharedHitBlocks": found["shared_hit"],
            "SharedReadBlocks": found["shared_read"],
            "Notes": "",
        })

        # Human-readable plan for the evidence file.
        txt = subprocess.run(
            ["docker", "exec", "-i", CONTAINER, "psql", "-U", "postgres", "-d", DB, "-c",
             f"EXPLAIN (ANALYZE, BUFFERS) {spec['sql']}"],
            capture_output=True, text=True,
        )
        plan_text.append(f"===== {qid} {spec['desc']} ({dataset_size} rows) =====\n{txt.stdout}")

    fieldnames = ["QueryID", "Description", "DatasetRows", "Phase", "PlanningTimeMs",
                  "ExecutionTimeMs", "ScanType", "IndexUsed", "RowsExamined", "RowsReturned",
                  "SharedHitBlocks", "SharedReadBlocks", "Notes"]
    all_rows = rows if args.phase == "before" else rows
    with out_file.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    plan_file.write_text("\n".join(plan_text))
    print(f"Phase '{args.phase}': recorded {len([r for r in rows if r['Phase']==args.phase])} queries")
    print(f"  -> {out_file}")
    print(f"  -> {plan_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
