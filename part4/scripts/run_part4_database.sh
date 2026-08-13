#!/usr/bin/env bash
# Apply the Part IV database extension to the existing Part III database.
#
#   bash scripts/run_part4_database.sh
#
# Additive and idempotent. It does not drop or recreate anything: the 36
# tables from Parts II and III are left exactly as they are.
set -euo pipefail

PART4="$(cd "$(dirname "$0")/.." && pwd)"
CONTAINER="${PG_CONTAINER:-part2-postgres}"
DB="${PG_DATABASE:-part3}"

echo "===== Part IV database extension ====="

if ! docker exec "$CONTAINER" pg_isready -U postgres >/dev/null 2>&1; then
    echo "Container $CONTAINER is not running. Start PostgreSQL first."
    exit 1
fi

for f in 01_part4_extension 02_part4_demo_context; do
    echo "  - $f.sql"
    docker cp "$PART4/db/$f.sql" "$CONTAINER:/tmp/$f.sql" >/dev/null
    docker exec "$CONTAINER" psql -U postgres -d "$DB" -q -v ON_ERROR_STOP=1 -f "/tmp/$f.sql"
done

echo ""
docker exec "$CONTAINER" psql -U postgres -d "$DB" -c "
SELECT 'base tables (excl. synthetic)' AS object, count(*)::text AS n
FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'
  AND table_name NOT LIKE 'perf_%'
UNION ALL SELECT 'ML_CLUSTER_INDICATOR_MAP rows', count(*)::text FROM ML_CLUSTER_INDICATOR_MAP
UNION ALL SELECT 'indexes', count(*)::text FROM pg_indexes WHERE schemaname='public'
UNION ALL SELECT 'materialized views', count(*)::text FROM pg_matviews WHERE schemaname='public';"

echo "===== Part IV extension applied ====="
