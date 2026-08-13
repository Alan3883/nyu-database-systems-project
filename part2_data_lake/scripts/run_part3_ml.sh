#!/usr/bin/env bash
# Run the Part III ML pipeline and load its results into PostgreSQL.
# Usage: bash scripts/run_part3_ml.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "===== Part III ML pipeline ====="
echo "[1/3] Training the DS010 theme model"
python3 -m ml.src.run_pipeline

echo ""
echo "[2/3] Loading results into PostgreSQL"
python3 scripts/load_ml_results_to_postgres.py

echo ""
echo "[3/3] Running the ML test suite"
python3 -m pytest ml/tests -q

echo ""
echo "===== ML pipeline complete ====="
python3 -c "
import json
m=json.load(open('ml/outputs/model_metrics.json'))
print(f\"  chunks       : {m['n_chunks']}\")
print(f\"  vocabulary   : {m['vocabulary_size']}\")
print(f\"  selected K   : {m['selected_k']}\")
print(f\"  silhouette   : {m['silhouette_score']}\")
print(f\"  cluster sizes: {m['cluster_sizes']}\")
"
