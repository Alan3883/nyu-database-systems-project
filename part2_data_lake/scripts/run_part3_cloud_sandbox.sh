#!/usr/bin/env bash
# =====================================================================
# Project Part III - Cloud Big Data analytics via BigQuery Sandbox
#
# WHY THIS SCRIPT EXISTS
# The full path (scripts/run_part3_cloud.sh) uses Cloud Storage plus
# BigQuery external tables, and Cloud Storage requires an active billing
# account. BigQuery Sandbox needs no billing account at all: it allows
# loading tables and running queries within a free monthly quota.
#
# This script therefore delivers the same requirement -- extract, filter,
# store, analyze, and present results on a public-cloud Big Data service --
# by loading the curated and ML tables straight into BigQuery from local
# files, skipping Cloud Storage.
#
# Requirements:
#   gcloud and bq installed, and: gcloud auth login
#   A GCP project. Billing is NOT required.
#
# Usage:
#   export GCP_PROJECT="your-project-id"
#   bash scripts/run_part3_cloud_sandbox.sh              # deploy
#   bash scripts/run_part3_cloud_sandbox.sh --dry-run    # preview only
# =====================================================================

set -euo pipefail

DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

: "${GCP_PROJECT:?Set GCP_PROJECT}"
BQ_DATASET="${BQ_DATASET:-part3_analytics}"
BQ_LOCATION="${BQ_LOCATION:-US}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EVIDENCE="$ROOT/architecture/cloud_evidence/part3"
mkdir -p "$EVIDENCE"
CMD_LOG="$EVIDENCE/sanitized_command_output.txt"
: > "$CMD_LOG"

mask() { sed -e "s/$GCP_PROJECT/<GCP_PROJECT>/g"; }
log()  { echo "$*" | mask | tee -a "$CMD_LOG"; }

log "===== Part III cloud analytics (BigQuery Sandbox) ====="
log "Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
log "Mode: BigQuery Sandbox, no Cloud Storage, no billing account required"
[ "$DRY_RUN" = "1" ] && log "DRY RUN: nothing will be created."

# ---------------------------------------------------------------------
# 1. Dataset
# ---------------------------------------------------------------------
log ""
log "--- Step 1: BigQuery dataset ---"
if [ "$DRY_RUN" = "1" ]; then
    log "Would create dataset $BQ_DATASET in $BQ_LOCATION"
elif bq --project_id="$GCP_PROJECT" show --dataset "$BQ_DATASET" >/dev/null 2>&1; then
    log "Dataset $BQ_DATASET already exists."
else
    log "Creating dataset $BQ_DATASET in $BQ_LOCATION"
    bq --project_id="$GCP_PROJECT" mk --dataset \
       --location="$BQ_LOCATION" \
       --description="Part III analytics over curated hybrid data and ML outputs" \
       "$GCP_PROJECT:$BQ_DATASET" 2>&1 | mask | tee -a "$CMD_LOG"
fi

# ---------------------------------------------------------------------
# 2. Load tables directly from local CSV.
#
# --autodetect infers the schema from the header row. Numeric-looking
# keys such as CountyFIPS may be typed as INTEGER, which drops leading
# zeros; every join in the queries below therefore casts to STRING, so the
# result is correct either way.
# ---------------------------------------------------------------------
log ""
log "--- Step 2: load tables from local files ---"

# An explicit schema can be supplied as a third argument.
#
# WHY THIS MATTERS: BigQuery's --autodetect infers column names from the header
# row only when the header's types differ from the data rows. In an all-string
# file such as dataset_catalog.csv, header and data look identical, so
# autodetect cannot recognise a header and falls back to string_field_0,
# string_field_1, ... which breaks every query that names a column. Declaring
# the schema explicitly removes the guesswork.
load_table() {
    local table="$1" file="$2" schema="${3:-}"
    if [ ! -f "$ROOT/$file" ]; then
        log "  SKIP (missing): $file"
        return 0
    fi
    local rows
    rows=$(($(wc -l < "$ROOT/$file") - 1))

    local -a opts=(--source_format=CSV --replace --skip_leading_rows=1
                   --allow_quoted_newlines --max_bad_records=0)
    if [ -n "$schema" ]; then
        log "  $table  <- $file  ($rows data rows, explicit schema)"
    else
        opts+=(--autodetect)
        log "  $table  <- $file  ($rows data rows, autodetect)"
    fi
    [ "$DRY_RUN" = "1" ] && return 0

    bq --project_id="$GCP_PROJECT" load "${opts[@]}" \
       "$GCP_PROJECT:$BQ_DATASET.$table" "$ROOT/$file" $schema 2>&1 \
       | grep -viE "^Upload|Waiting|^$" | mask | tee -a "$CMD_LOG" || true
}

CATALOG_SCHEMA="DatasetID:STRING,DatasetName:STRING,SourceOrganization:STRING,\
SourceURL:STRING,FileFormat:STRING,DataClassification:STRING,GeographicLevel:STRING,\
TimePeriod:STRING,MainSubject:STRING,KeyFields:STRING,StorageZone:STRING,\
RelatedEDAEntity:STRING,UpdateFrequency:STRING,License:STRING,Notes:STRING"

load_table "geographic_area"        "curated/geographic_area.csv"
load_table "health_indicator"       "curated/health_indicator.csv"
load_table "health_observation"     "curated/health_observation_sample.csv"
load_table "dataset_catalog"        "metadata/dataset_catalog.csv"  "$CATALOG_SCHEMA"
load_table "data_asset"             "curated/data_asset.csv"
load_table "ml_cluster_assignments" "ml/outputs/cluster_assignments.csv"
load_table "ml_cluster_summary"     "ml/outputs/cluster_summary.csv"

if [ "$DRY_RUN" = "1" ]; then
    log ""
    log "DRY RUN complete. Nothing was created."
    exit 0
fi

# ---------------------------------------------------------------------
# 3. Table inventory with row counts.
# ---------------------------------------------------------------------
log ""
log "--- Step 3: table inventory ---"
{
  echo "TableName,RowCount"
  for t in geographic_area health_indicator health_observation dataset_catalog \
           data_asset ml_cluster_assignments ml_cluster_summary; do
      n=$(bq --project_id="$GCP_PROJECT" query --use_legacy_sql=false --format=csv \
            "SELECT COUNT(*) FROM \`$GCP_PROJECT.$BQ_DATASET.$t\`" 2>/dev/null | tail -1)
      echo "$t,${n:-error}"
  done
} > "$EVIDENCE/object_inventory.csv"
cat "$EVIDENCE/object_inventory.csv" | tee -a "$CMD_LOG"

# ---------------------------------------------------------------------
# 4. Analytical queries: extract, filter, analyze, present.
# ---------------------------------------------------------------------
log ""
log "--- Step 4: analytical queries ---"
: > "$EVIDENCE/analytics_results.csv"

run_query() {
    local n="$1" title="$2" sql="$3"
    log ""
    log "QUERY $n: $title"
    {
      echo ""
      echo "### QUERY $n: $title"
    } >> "$EVIDENCE/analytics_results.csv"
    bq --project_id="$GCP_PROJECT" query --use_legacy_sql=false \
       --format=csv --max_rows=100 "$sql" 2>/dev/null \
       | tee -a "$EVIDENCE/analytics_results.csv" | head -12 | mask | tee -a "$CMD_LOG"
}

run_query 1 "Indicators and observations by geographic level" "
SELECT g.GeographyType,
       COUNT(DISTINCT g.GeographyID) AS geographies,
       COUNT(DISTINCT o.IndicatorID) AS distinct_indicators,
       COUNT(o.ObservationID)        AS observations
FROM \`$GCP_PROJECT.$BQ_DATASET.geographic_area\` g
LEFT JOIN \`$GCP_PROJECT.$BQ_DATASET.health_observation\` o
  ON CAST(o.GeographyID AS STRING) = CAST(g.GeographyID AS STRING)
GROUP BY g.GeographyType
ORDER BY geographies DESC"

run_query 2 "Health indicators summarized by state" "
SELECT g.StateCode, i.IndicatorName, i.FactorCategory,
       COUNT(*) AS county_observations,
       ROUND(AVG(CAST(o.MeasureValue AS FLOAT64)), 2) AS avg_value,
       ROUND(MIN(CAST(o.MeasureValue AS FLOAT64)), 2) AS min_value,
       ROUND(MAX(CAST(o.MeasureValue AS FLOAT64)), 2) AS max_value
FROM \`$GCP_PROJECT.$BQ_DATASET.health_observation\` o
JOIN \`$GCP_PROJECT.$BQ_DATASET.health_indicator\` i
  ON CAST(i.IndicatorID AS STRING) = CAST(o.IndicatorID AS STRING)
JOIN \`$GCP_PROJECT.$BQ_DATASET.geographic_area\` g
  ON CAST(g.GeographyID AS STRING) = CAST(o.GeographyID AS STRING)
WHERE g.GeographyType = 'County'
GROUP BY g.StateCode, i.IndicatorName, i.FactorCategory
HAVING COUNT(*) >= 2
ORDER BY avg_value DESC
LIMIT 40"

run_query 3 "ML clusters with chunk counts and top terms" "
SELECT s.ClusterID, s.SuggestedLabel, s.ChunkCount,
       COUNT(a.ChunkIndex) AS verified_chunks,
       ROUND(AVG(CAST(a.DistanceToCentroid AS FLOAT64)), 4) AS avg_distance,
       COUNT(DISTINCT a.PageNumber) AS source_pages,
       s.HumanReviewed
FROM \`$GCP_PROJECT.$BQ_DATASET.ml_cluster_summary\` s
LEFT JOIN \`$GCP_PROJECT.$BQ_DATASET.ml_cluster_assignments\` a
  ON CAST(a.ClusterID AS STRING) = CAST(s.ClusterID AS STRING)
GROUP BY s.ClusterID, s.SuggestedLabel, s.ChunkCount, s.HumanReviewed
ORDER BY s.ClusterID"

run_query 4 "Dataset lineage and licence inventory" "
SELECT c.DatasetID, c.DatasetName, c.SourceOrganization,
       c.DataClassification, c.GeographicLevel, c.License,
       COUNT(a.AssetID) AS asset_count,
       SUM(CAST(a.FileSizeBytes AS INT64)) AS total_bytes
FROM \`$GCP_PROJECT.$BQ_DATASET.dataset_catalog\` c
LEFT JOIN \`$GCP_PROJECT.$BQ_DATASET.data_asset\` a
  ON a.DatasetID = c.DatasetID
GROUP BY c.DatasetID, c.DatasetName, c.SourceOrganization,
         c.DataClassification, c.GeographicLevel, c.License
ORDER BY c.DatasetID"

# ---------------------------------------------------------------------
# 5. Resource inventory.
# ---------------------------------------------------------------------
TABLE_COUNT=$(($(wc -l < "$EVIDENCE/object_inventory.csv") - 1))

cat > "$EVIDENCE/resource_inventory.md" <<INVENTORY
# Part III Cloud Resource Inventory

Generated by \`scripts/run_part3_cloud_sandbox.sh\` on $(date -u +%Y-%m-%dT%H:%M:%SZ).
The project name is masked.

## Deployment mode

**BigQuery Sandbox.** No billing account is attached to the project. Cloud Storage was not
used, because it requires billing. Tables were loaded into BigQuery directly from local
curated files, which delivers the same extract / filter / store / analyze / present path on a
public-cloud Big Data service.

## Deployed

| Resource | Type | Location | Detail |
|----------|------|----------|--------|
| BigQuery dataset | BigQuery | $BQ_LOCATION | \`$BQ_DATASET\`, $TABLE_COUNT loaded tables |

## Loaded tables

See \`object_inventory.csv\` for the row count of each table.

| Table | Source file |
|-------|-------------|
| geographic_area | curated/geographic_area.csv |
| health_indicator | curated/health_indicator.csv |
| health_observation | curated/health_observation_sample.csv |
| dataset_catalog | metadata/dataset_catalog.csv |
| data_asset | curated/data_asset.csv |
| ml_cluster_assignments | ml/outputs/cluster_assignments.csv |
| ml_cluster_summary | ml/outputs/cluster_summary.csv |

## Analytical queries executed

1. Indicators and observations by geographic level
2. Health indicators summarized by state
3. ML clusters with chunk counts and top terms
4. Dataset lineage and licence inventory

Results are in \`analytics_results.csv\`.

## Deliberately NOT uploaded

Credentials, service-account keys, PostgreSQL passwords, database volume files, full raw
datasets, the DS010 PDF binary, synthetic performance data.

## NOT deployed (future state only)

Cloud Storage (needs billing), Cloud SQL, Cloud Data Fusion, Dataplex, Vertex AI, Pub/Sub,
Dataflow, Looker Studio. These appear in
\`architecture/diagrams/part3_future_state_architecture.mmd\` marked as planned.

## Sandbox limitations

- Tables expire automatically after 60 days.
- No Cloud Storage integration, so external tables are not used.
- Free monthly quota: 1 TB of query processing and 10 GB of storage. This project uses far
  less than either.
INVENTORY

log ""
log "===== Cloud analytics complete ====="
log "Evidence written to architecture/cloud_evidence/part3/"
echo ""
echo "Files created:"
ls -1 "$EVIDENCE"
