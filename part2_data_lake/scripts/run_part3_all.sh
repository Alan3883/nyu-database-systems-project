#!/usr/bin/env bash
# Run the complete Part III pipeline end to end.
# Cloud deployment is NOT included; it needs credentials and is run separately
# with scripts/run_part3_cloud.sh.
# Usage: bash scripts/run_part3_all.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "############################################################"
echo "# Project Part III - full local pipeline"
echo "############################################################"

echo ""
echo "### 1. Data lake validation (Part II pipeline)"
python3 scripts/01_inventory_data.py 2>&1 | tail -1
python3 scripts/02_profile_data.py   2>&1 | tail -1
python3 scripts/03_build_curated_data.py 2>&1 | tail -1
python3 scripts/04_validate_outputs.py   2>&1 | tail -1

echo ""
echo "### 2. Database build"
bash scripts/run_part3_database.sh

echo ""
echo "### 3. ML pipeline"
bash scripts/run_part3_ml.sh

echo ""
echo "### 4. Performance measurement"
python3 scripts/run_performance_tests.py --phase after 2>&1 | tail -3

echo ""
echo "### 5. Database tests"
python3 -m pytest database/tests/test_database.py -q 2>&1 | tail -2

echo ""
echo "### 6. Validation"
python3 scripts/validate_part3.py

echo ""
echo "############################################################"
echo "# Complete. Cloud deployment: bash scripts/run_part3_cloud.sh"
echo "############################################################"
