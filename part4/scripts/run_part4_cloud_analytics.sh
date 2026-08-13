#!/usr/bin/env bash
# =====================================================================
# Part IV cloud analytics on BigQuery Sandbox.
#
#   bash scripts/run_part4_cloud_analytics.sh
#
# Part III loaded the curated public-health tables and the Part III model
# output into the sandbox dataset part3_analytics. Part IV adds the two
# tables the end-to-end solution produces and that the OLTP database
# should not be asked to serve analytically:
#
#   part4_ml_run              the model run register, including failures
#   part4_approved_insight    the governed cluster-to-indicator mappings
#
# Separation of concerns: PostgreSQL runs the transactional workload,
# BigQuery answers portfolio and governance questions across runs. No
# customer, quote, contract, or payment row is ever exported. Only
# aggregate public-health data and model governance metadata leave the
# operational database.
#
# Requires an authenticated `bq`. Sandbox only: no billing account, no
# Cloud Storage, no service-account key.
# =====================================================================
set -euo pipefail

PART4="$(cd "$(dirname "$0")/.." && pwd)"
DATASET="${BQ_DATASET:-part3_analytics}"
OUT="$PART4/evidence/cloud"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$OUT"

if ! command -v bq >/dev/null 2>&1; then
    echo "bq is not installed. Skipping cloud analytics."
    exit 0
fi
PROJECT="$(gcloud config get-value project 2>/dev/null)"
if [ -z "$PROJECT" ]; then
    echo "No gcloud project configured. Skipping cloud analytics."
    exit 0
fi

LOG="$OUT/part4_cloud_output.txt"
{
echo "===== Part IV cloud analytics (BigQuery Sandbox) ====="
echo "Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Dataset: $DATASET"
echo "Mode: sandbox, no Cloud Storage, no billing account"
echo ""

echo "--- Step 1: export governance metadata from PostgreSQL ---"
docker exec part2-postgres psql -U postgres -d part3 -At -F',' -c "
COPY (
  SELECT MLRunID, ModelName, ModelVersion, Algorithm, Status,
         StartedAt, CompletedAt,
         COALESCE(MetricsJSON->>'source_asset_version','') AS SourceAssetVersion,
         COALESCE(MetricsJSON->>'source_sha256','')        AS SourceSHA256,
         COALESCE(MetricsJSON->>'selected_k','')           AS SelectedK,
         COALESCE(MetricsJSON->>'silhouette_score','')     AS Silhouette,
         COALESCE(MetricsJSON->>'n_chunks','')             AS Chunks,
         COALESCE(MetricsJSON->>'error','')                AS ErrorMessage
  FROM ML_RUN ORDER BY MLRunID
) TO STDOUT WITH (FORMAT csv, HEADER true);" > "$STAGE/part4_ml_run.csv"
echo "  part4_ml_run.csv        $(( $(wc -l < "$STAGE/part4_ml_run.csv") - 1 )) rows"

docker exec part2-postgres psql -U postgres -d part3 -At -F',' -c "
COPY (
  SELECT m.MLRunID, m.ClusterID, s.ClusterLabel,
         m.HealthIndicatorID, hi.IndicatorName, hi.FactorCategory,
         m.ApprovedBy, m.ApprovedAt, m.IsActive, s.HumanReviewed
  FROM ML_CLUSTER_INDICATOR_MAP m
  JOIN ML_CLUSTER_SUMMARY s
    ON s.MLRunID = m.MLRunID AND s.ClusterID = m.ClusterID
  JOIN HEALTH_INDICATOR hi ON hi.IndicatorID = m.HealthIndicatorID
  ORDER BY m.MLRunID, m.ClusterID
) TO STDOUT WITH (FORMAT csv, HEADER true);" > "$STAGE/part4_approved_insight.csv"
echo "  part4_approved_insight.csv  $(( $(wc -l < "$STAGE/part4_approved_insight.csv") - 1 )) rows"
echo ""

echo "--- Step 2: load into BigQuery ---"
bq --project_id="$PROJECT" load --replace --source_format=CSV --skip_leading_rows=1 \
   --autodetect "$DATASET.part4_ml_run" "$STAGE/part4_ml_run.csv" 2>&1 | tail -1
bq --project_id="$PROJECT" load --replace --source_format=CSV --skip_leading_rows=1 \
   --autodetect "$DATASET.part4_approved_insight" "$STAGE/part4_approved_insight.csv" 2>&1 | tail -1
echo ""

echo "--- Step 3: table inventory ---"
bq --project_id="$PROJECT" query --use_legacy_sql=false --format=csv "
SELECT table_id AS TableName, row_count AS RowCount
FROM \`$PROJECT.$DATASET.__TABLES__\`
ORDER BY table_id" 2>/dev/null
echo ""

echo "--- Step 4: Part IV analytical queries ---"
echo ""
echo "QUERY A: model run register, including runs that failed"
bq --project_id="$PROJECT" query --use_legacy_sql=false --format=csv "
SELECT ModelVersion, Status, SourceAssetVersion, SelectedK, Silhouette,
       Chunks, SUBSTR(IFNULL(ErrorMessage,''), 1, 48) AS Error
FROM \`$PROJECT.$DATASET.part4_ml_run\`
ORDER BY MLRunID" 2>/dev/null
echo ""

echo "QUERY B: governance posture, one row per run"
bq --project_id="$PROJECT" query --use_legacy_sql=false --format=csv "
SELECT r.ModelVersion, r.Status,
       COUNT(i.ClusterID)                                        AS mapped_clusters,
       COUNTIF(i.IsActive AND i.HumanReviewed)                   AS approved_insights,
       COUNTIF(i.IsActive AND NOT i.HumanReviewed)               AS ungoverned_insights
FROM \`$PROJECT.$DATASET.part4_ml_run\` r
LEFT JOIN \`$PROJECT.$DATASET.part4_approved_insight\` i
  ON i.MLRunID = r.MLRunID
GROUP BY r.ModelVersion, r.Status, r.MLRunID
ORDER BY r.MLRunID" 2>/dev/null
echo ""

echo "QUERY C: approved themes joined to the public-health indicators they explain"
bq --project_id="$PROJECT" query --use_legacy_sql=false --format=csv "
SELECT i.ClusterLabel, i.IndicatorName, i.FactorCategory, i.ApprovedBy,
       COUNT(o.MeasureValue)                AS county_observations,
       ROUND(AVG(o.MeasureValue), 2)        AS avg_value
FROM \`$PROJECT.$DATASET.part4_approved_insight\` i
LEFT JOIN \`$PROJECT.$DATASET.health_observation\` o
  ON o.IndicatorID = i.HealthIndicatorID
WHERE i.IsActive AND i.HumanReviewed
GROUP BY 1, 2, 3, 4
ORDER BY county_observations DESC" 2>/dev/null
echo ""

echo "QUERY D: regional distribution of the indicators behind approved themes"
bq --project_id="$PROJECT" query --use_legacy_sql=false --format=csv "
SELECT g.StateCode, i.IndicatorName,
       COUNT(*)                      AS counties,
       ROUND(AVG(o.MeasureValue), 2) AS avg_value
FROM \`$PROJECT.$DATASET.part4_approved_insight\` i
JOIN \`$PROJECT.$DATASET.health_observation\` o ON o.IndicatorID = i.HealthIndicatorID
JOIN \`$PROJECT.$DATASET.geographic_area\`     g ON g.GeographyID = o.GeographyID
WHERE i.IsActive AND i.HumanReviewed AND g.StateCode IS NOT NULL
GROUP BY 1, 2
ORDER BY avg_value DESC
LIMIT 15" 2>/dev/null
echo ""
echo "===== Part IV cloud analytics complete ====="
} 2>&1 | tee "$LOG"

echo ""
echo "Evidence written to $OUT/part4_cloud_output.txt"
