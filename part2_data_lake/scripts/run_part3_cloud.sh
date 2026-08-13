#!/usr/bin/env bash
# =====================================================================
# Project Part III - Google Cloud deployment
#
# Uploads Part III outputs to Cloud Storage under a part3/ prefix, then
# creates a BigQuery dataset and runs the analytical queries.
#
# PRESERVATION RULE: this script only ever writes under the part3/
# prefix. It never deletes or moves anything already in the bucket.
#
# Requirements:
#   gcloud and bq installed, and: gcloud auth login
#   A project with billing enabled.
#
# Usage:
#   export GCP_PROJECT="your-project-id"
#   export GCS_BUCKET="your-bucket-name"
#   bash scripts/run_part3_cloud.sh
#
# Optional:
#   export BQ_DATASET="part3_analytics"   # default
#   export GCS_LOCATION="us-east1"        # used only if the bucket is new
# =====================================================================

set -euo pipefail

# --dry-run prints every action without creating or uploading anything.
# Use it to preview the plan before spending anything.
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

: "${GCP_PROJECT:?Set GCP_PROJECT}"
: "${GCS_BUCKET:?Set GCS_BUCKET}"
BQ_DATASET="${BQ_DATASET:-part3_analytics}"
DEFAULT_LOCATION="${GCS_LOCATION:-us-east1}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EVIDENCE="$ROOT/architecture/cloud_evidence/part3"
mkdir -p "$EVIDENCE"
CMD_LOG="$EVIDENCE/sanitized_command_output.txt"
: > "$CMD_LOG"

mask() { sed -e "s/$GCP_PROJECT/<GCP_PROJECT>/g" -e "s/$GCS_BUCKET/<GCS_BUCKET>/g"; }
log()  { echo "$*" | mask | tee -a "$CMD_LOG"; }
run()  { log "\$ $*"; "$@" 2>&1 | mask | tee -a "$CMD_LOG"; }

log "===== Part III cloud deployment ====="
log "Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# ---------------------------------------------------------------------
# 1. Bucket. Created only if absent; existing contents are never touched.
# ---------------------------------------------------------------------
log ""
log "--- Step 1: Cloud Storage bucket ---"
if [ "$DRY_RUN" = "1" ]; then
    log "DRY RUN: no bucket, dataset, upload, or query will be created."
fi

if gcloud storage buckets describe "gs://$GCS_BUCKET" --project "$GCP_PROJECT" >/dev/null 2>&1; then
    log "Bucket exists. Existing objects will not be modified."
    EXISTING=$(gcloud storage ls -r "gs://$GCS_BUCKET/**" --project "$GCP_PROJECT" 2>/dev/null | grep -c '^gs://' || true)
    log "Objects already present: $EXISTING"
else
    log "Bucket not found. Would create in $DEFAULT_LOCATION."
    [ "$DRY_RUN" = "1" ] || run gcloud storage buckets create "gs://$GCS_BUCKET" \
        --project "$GCP_PROJECT" --location "$DEFAULT_LOCATION" \
        --uniform-bucket-level-access
fi

# The BigQuery dataset must sit in a location compatible with the bucket.
# Inspect it rather than assuming.
BUCKET_LOCATION=$(gcloud storage buckets describe "gs://$GCS_BUCKET" \
    --project "$GCP_PROJECT" --format="value(location)" 2>/dev/null || true)
BUCKET_LOCATION="${BUCKET_LOCATION:-$DEFAULT_LOCATION}"
log "Bucket location (inspected, not assumed): $BUCKET_LOCATION"

# ---------------------------------------------------------------------
# 2. Upload under part3/ only.
# ---------------------------------------------------------------------
log ""
log "--- Step 2: upload Part III outputs ---"

# A single file lands directly under the destination prefix.
#
# A directory needs `rsync`, not `cp -r`. `gcloud storage cp -r dir gs://b/p/`
# copies the directory itself into the prefix, producing gs://b/p/dir/file,
# which would break the BigQuery external table URIs below. `rsync` mirrors the
# directory *contents* into the prefix, which is what the URIs expect.
upload_file() {
    local src="$1" dest="$2"
    if [ -f "$ROOT/$src" ]; then
        log "  file $src -> gs://<GCS_BUCKET>/$dest"
        [ "$DRY_RUN" = "1" ] && return 0
        gcloud storage cp "$ROOT/$src" "gs://$GCS_BUCKET/$dest" \
            --project "$GCP_PROJECT" >/dev/null 2>&1
    else
        log "  SKIP (missing file): $src"
    fi
}

upload_dir() {
    local src="$1" dest="$2"
    if [ -d "$ROOT/$src" ]; then
        log "  dir  $src/ -> gs://<GCS_BUCKET>/$dest/"
        [ "$DRY_RUN" = "1" ] && return 0
        gcloud storage rsync -r "$ROOT/$src" "gs://$GCS_BUCKET/$dest" \
            --project "$GCP_PROJECT" >/dev/null 2>&1
    else
        log "  SKIP (missing dir): $src"
    fi
}

# Curated tables must land at gs://<bucket>/part3/curated/<file>.csv exactly,
# because bigquery_analytics.sql references those URIs.
upload_dir  "curated"                          "part3/curated"
upload_file "metadata/dataset_catalog.csv"     "part3/metadata/dataset_catalog.csv"
upload_file "metadata/data_dictionary.csv"     "part3/metadata/data_dictionary.csv"
upload_file "metadata/lineage.csv"             "part3/metadata/lineage.csv"
upload_file "metadata/data_quality_report.csv" "part3/metadata/data_quality_report.csv"
upload_file "ml/outputs/cluster_assignments.csv"   "part3/ml/outputs/cluster_assignments.csv"
upload_file "ml/outputs/cluster_summary.csv"       "part3/ml/outputs/cluster_summary.csv"
upload_file "ml/outputs/top_terms_by_cluster.csv"  "part3/ml/outputs/top_terms_by_cluster.csv"
upload_file "ml/outputs/representative_chunks.csv" "part3/ml/outputs/representative_chunks.csv"
upload_file "ml/outputs/model_metrics.json"        "part3/ml/outputs/model_metrics.json"
upload_file "ml/outputs/cluster_visualization.png" "part3/ml/outputs/cluster_visualization.png"
upload_file "ml/outputs/top_terms_by_cluster.png"  "part3/ml/outputs/top_terms_by_cluster.png"
upload_file "ml/models/model_metadata.json"        "part3/ml/model_metadata/model_metadata.json"
upload_file "database/evidence/performance_results.csv" "part3/database/performance/performance_results.csv"
upload_file "database/evidence/query_plan_summary.md"   "part3/database/performance/query_plan_summary.md"
upload_dir  "database/physical"                        "part3/database/physical_design"
upload_dir  "architecture/diagrams"                    "part3/architecture/diagrams"

# NOT uploaded, by design: credentials, service-account keys, database
# volumes, full raw datasets, the DS010 PDF binary.

# ---------------------------------------------------------------------
# 3. BigQuery dataset in a location compatible with the bucket.
# ---------------------------------------------------------------------
log ""
log "--- Step 3: BigQuery dataset ---"
if [ "$DRY_RUN" = "1" ]; then
    log "DRY RUN: would create BigQuery dataset $BQ_DATASET in $BUCKET_LOCATION"
elif bq --project_id="$GCP_PROJECT" show --dataset "$BQ_DATASET" >/dev/null 2>&1; then
    log "Dataset $BQ_DATASET already exists."
else
    run bq --project_id="$GCP_PROJECT" mk --dataset \
        --location="$BUCKET_LOCATION" \
        --description="Part III analytics over curated hybrid data and ML outputs" \
        "$GCP_PROJECT:$BQ_DATASET"
fi

# ---------------------------------------------------------------------
# 4. Create tables and run the analytical queries.
# ---------------------------------------------------------------------
log ""
log "--- Step 4: create tables and run analytics ---"

if [ "$DRY_RUN" = "1" ]; then
    log ""
    log "DRY RUN complete. Nothing was created. Re-run without --dry-run to deploy."
    exit 0
fi

SQL_SRC="$ROOT/database/queries/bigquery_analytics.sql"
SQL_TMP="$(mktemp)"
sed -e "s/\${PROJECT}/$GCP_PROJECT/g" \
    -e "s/\${DATASET}/$BQ_DATASET/g" \
    -e "s/\${BUCKET}/$GCS_BUCKET/g" "$SQL_SRC" > "$SQL_TMP"

# Split on the section marker: DDL first, then the queries.
DDL=$(awk '/SECTION 2/{exit} {print}' "$SQL_TMP")
log "Creating external tables..."
echo "$DDL" | bq --project_id="$GCP_PROJECT" query --use_legacy_sql=false 2>&1 | mask | tee -a "$CMD_LOG"

# Table inventory with row counts.
log ""
log "Table inventory:"
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

# Run the three required analytical queries and export results.
log ""
log "Running analytical queries..."
: > "$EVIDENCE/analytics_results.csv"

run_query() {
    local n="$1" title="$2" sql="$3"
    log ""
    log "QUERY $n: $title"
    echo "" >> "$EVIDENCE/analytics_results.csv"
    echo "### QUERY $n: $title" >> "$EVIDENCE/analytics_results.csv"
    bq --project_id="$GCP_PROJECT" query --use_legacy_sql=false --format=csv --max_rows=100 \
       "$sql" 2>&1 | tee -a "$EVIDENCE/analytics_results.csv" | head -12 | mask | tee -a "$CMD_LOG"
}

run_query 1 "Indicators and observations by geographic level" "
SELECT g.GeographyType, COUNT(DISTINCT g.GeographyID) AS geographies,
       COUNT(DISTINCT o.IndicatorID) AS distinct_indicators,
       COUNT(o.ObservationID) AS observations
FROM \`$GCP_PROJECT.$BQ_DATASET.geographic_area\` g
LEFT JOIN \`$GCP_PROJECT.$BQ_DATASET.health_observation\` o
  ON CAST(o.GeographyID AS STRING)=CAST(g.GeographyID AS STRING)
GROUP BY g.GeographyType ORDER BY geographies DESC"

run_query 2 "Health indicators summarized by state" "
SELECT g.StateCode, i.IndicatorName, i.FactorCategory, COUNT(*) AS county_observations,
       ROUND(AVG(CAST(o.MeasureValue AS FLOAT64)),2) AS avg_value
FROM \`$GCP_PROJECT.$BQ_DATASET.health_observation\` o
JOIN \`$GCP_PROJECT.$BQ_DATASET.health_indicator\` i
  ON CAST(i.IndicatorID AS STRING)=CAST(o.IndicatorID AS STRING)
JOIN \`$GCP_PROJECT.$BQ_DATASET.geographic_area\` g
  ON CAST(g.GeographyID AS STRING)=CAST(o.GeographyID AS STRING)
WHERE g.GeographyType='County'
GROUP BY g.StateCode, i.IndicatorName, i.FactorCategory
HAVING COUNT(*)>=2 ORDER BY avg_value DESC LIMIT 40"

run_query 3 "ML clusters with chunk counts and top terms" "
SELECT s.ClusterID, s.SuggestedLabel, s.ChunkCount,
       COUNT(a.ChunkIndex) AS verified_chunks,
       ROUND(AVG(CAST(a.DistanceToCentroid AS FLOAT64)),4) AS avg_distance,
       COUNT(DISTINCT a.PageNumber) AS source_pages, s.HumanReviewed
FROM \`$GCP_PROJECT.$BQ_DATASET.ml_cluster_summary\` s
LEFT JOIN \`$GCP_PROJECT.$BQ_DATASET.ml_cluster_assignments\` a
  ON CAST(a.ClusterID AS STRING)=CAST(s.ClusterID AS STRING)
GROUP BY s.ClusterID, s.SuggestedLabel, s.ChunkCount, s.HumanReviewed
ORDER BY s.ClusterID"

rm -f "$SQL_TMP"

# ---------------------------------------------------------------------
# 5. Resource inventory.
# ---------------------------------------------------------------------
log ""
log "--- Step 5: resource inventory ---"
UPLOADED=$(gcloud storage ls -r "gs://$GCS_BUCKET/part3/**" --project "$GCP_PROJECT" 2>/dev/null | grep -c '^gs://' || echo 0)

cat > "$EVIDENCE/resource_inventory.md" <<INVENTORY
# Part III Cloud Resource Inventory

Generated by \`scripts/run_part3_cloud.sh\` on $(date -u +%Y-%m-%dT%H:%M:%SZ).
Project and bucket names are masked.

## Deployed

| Resource | Type | Location | Detail |
|----------|------|----------|--------|
| Cloud Storage bucket | GCS | $BUCKET_LOCATION | Uniform bucket-level access, private |
| part3/ prefix | GCS prefix | $BUCKET_LOCATION | $UPLOADED objects uploaded |
| BigQuery dataset | BigQuery | $BUCKET_LOCATION | \`$BQ_DATASET\`, 7 external tables |

## Uploaded content

| Prefix | Content |
|--------|---------|
| part3/curated/ | 5 curated tables |
| part3/metadata/ | catalog, dictionary, lineage, quality report |
| part3/ml/outputs/ | cluster assignments, summary, top terms, metrics, 2 PNG |
| part3/ml/model_metadata/ | model metadata with prohibited-use declarations |
| part3/database/performance/ | performance results and query plan analysis |
| part3/database/physical_design/ | physical DDL files |
| part3/architecture/ | architecture diagram sources and SVG |

## Deliberately NOT uploaded

Credentials, service-account keys, PostgreSQL passwords, database volume files,
full raw datasets, the DS010 PDF binary, synthetic performance data.

## NOT deployed (future state only)

Cloud SQL, Cloud Data Fusion, Dataplex, Vertex AI, Pub/Sub, Dataflow, Looker Studio.
These appear in \`architecture/diagrams/part3_future_state_architecture.mmd\` marked as
planned.
INVENTORY

log "Objects under part3/: $UPLOADED"
log ""
log "===== Cloud deployment complete ====="
log "Evidence written to architecture/cloud_evidence/part3/"
echo ""
echo "Files created:"
ls -1 "$EVIDENCE"
