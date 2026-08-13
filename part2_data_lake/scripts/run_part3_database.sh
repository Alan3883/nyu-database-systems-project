#!/usr/bin/env bash
# Build the Part III database from scratch: Part II schema + Part III physical layer.
# Usage: bash scripts/run_part3_database.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONTAINER="${PG_CONTAINER:-part2-postgres}"
DB="${PG_DATABASE:-part3}"

echo "===== Part III database build ====="

if ! docker exec "$CONTAINER" pg_isready -U postgres >/dev/null 2>&1; then
    echo "Container $CONTAINER is not running. Start it with:"
    echo "  docker run -d --name $CONTAINER -e POSTGRES_PASSWORD=<your-password> -p 5432:5432 postgres:16"
    exit 1
fi

echo "[1/6] Recreating database $DB"
docker exec "$CONTAINER" psql -U postgres -q -c "DROP DATABASE IF EXISTS $DB;" -c "CREATE DATABASE $DB;"

echo "[2/6] Loading the Part II logical schema (26 tables)"
docker cp "$ROOT/logical_model/logical_schema.sql" "$CONTAINER:/tmp/logical_schema.sql" >/dev/null
docker exec "$CONTAINER" psql -U postgres -d "$DB" -q -v ON_ERROR_STOP=1 -f /tmp/logical_schema.sql

echo "[3/6] Loading curated data"
python3 "$ROOT/scripts/load_curated_to_postgres.py" 2>&1 | tail -3

echo "[4/6] Applying the Part III physical layer"
for f in 01_physical_schema 03_workflow_extension 04_ml_metadata_extension \
         02_indexes 05_materialized_views 06_permissions; do
    echo "  - $f.sql"
    docker cp "$ROOT/database/physical/$f.sql" "$CONTAINER:/tmp/$f.sql" >/dev/null
    docker exec "$CONTAINER" psql -U postgres -d "$DB" -q -v ON_ERROR_STOP=1 -f "/tmp/$f.sql"
done

echo "[5/6] Building the synthetic performance dataset (500k rows)"
docker cp "$ROOT/database/physical/07_partitioning_and_clustering.sql" "$CONTAINER:/tmp/07.sql" >/dev/null
docker exec "$CONTAINER" psql -U postgres -d "$DB" -q -v ON_ERROR_STOP=1 -f /tmp/07.sql

echo "[6/6] Refreshing the materialized view"
docker exec "$CONTAINER" psql -U postgres -d "$DB" -q \
    -c "REFRESH MATERIALIZED VIEW MV_ACCOUNT_REGIONAL_HEALTH_PROFILE;" -c "ANALYZE;"

echo ""
echo "===== Build complete ====="
docker exec "$CONTAINER" psql -U postgres -d "$DB" -c "
SELECT 'base tables (excl. synthetic)' AS object, count(*)::text AS n
FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'
  AND table_name NOT LIKE 'perf_%'
UNION ALL SELECT 'foreign keys', count(*)::text FROM information_schema.table_constraints
  WHERE constraint_type='FOREIGN KEY' AND table_schema='public'
UNION ALL SELECT 'indexes', count(*)::text FROM pg_indexes WHERE schemaname='public'
UNION ALL SELECT 'materialized views', count(*)::text FROM pg_matviews WHERE schemaname='public';"
