#!/usr/bin/env bash
# Upload project samples and metadata to Google Cloud Storage.
# This script uploads only small sample and metadata files by default.
# It does not upload full raw datasets.
#
# Requirements:
#   - Google Cloud CLI (gcloud) installed and logged in: gcloud auth login
#   - A Google Cloud project with billing enabled.
#   - The environment variables below set. Do not hard-code secrets.
#
# Usage:
#   export GCP_PROJECT="your-project-id"
#   export GCS_BUCKET="part2-datalake-yourname"     # bucket names are global
#   ./gcloud_upload.sh
#
# Notes:
#   - Your account needs the "Storage Admin" role on the project
#     (or "Storage Object Admin" on an existing bucket).
#   - Bucket names must be globally unique, lowercase, no underscores.

set -euo pipefail

: "${GCP_PROJECT:?Set GCP_PROJECT}"
: "${GCS_BUCKET:?Set GCS_BUCKET}"
LOCATION="${GCS_LOCATION:-us-east1}"

# Root of the data lake (parent of this architecture folder).
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EVIDENCE_DIR="$ROOT/architecture/cloud_evidence"
mkdir -p "$EVIDENCE_DIR"
CMD_LOG="$EVIDENCE_DIR/gcloud_commands_used.txt"
: > "$CMD_LOG"

log_cmd () {
  # Record the command with the project and bucket names masked.
  echo "$*" | sed -e "s/$GCP_PROJECT/<GCP_PROJECT>/g" -e "s/$GCS_BUCKET/<GCS_BUCKET>/g" >> "$CMD_LOG"
}

echo "Creating bucket if it does not exist..."
log_cmd gcloud storage buckets create "gs://$GCS_BUCKET" --project "$GCP_PROJECT" --location "$LOCATION" --uniform-bucket-level-access
if ! gcloud storage buckets describe "gs://$GCS_BUCKET" --project "$GCP_PROJECT" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://$GCS_BUCKET" \
    --project "$GCP_PROJECT" \
    --location "$LOCATION" \
    --uniform-bucket-level-access >/dev/null
fi

upload_dir () {
  local local_dir="$1"
  local dest_prefix="$2"
  if [ -d "$ROOT/$local_dir" ]; then
    echo "Uploading $local_dir -> gs://$GCS_BUCKET/$dest_prefix/"
    log_cmd gcloud storage cp -r "$ROOT/$local_dir" "gs://$GCS_BUCKET/"
    gcloud storage cp -r "$ROOT/$local_dir" "gs://$GCS_BUCKET/" \
      --project "$GCP_PROJECT" >/dev/null 2>&1
  fi
}

# Upload metadata, curated tables, and small samples. Keep folder structure.
upload_dir "metadata"    "metadata"
upload_dir "curated"     "curated"
upload_dir "sample_data" "sample_data"

# Save cloud evidence: object list as manifest and a validation summary.
# No secrets are written. Only names, sizes, and dates.
echo "Saving cloud evidence to architecture/cloud_evidence/ ..."
log_cmd gcloud storage ls -l -r "gs://$GCS_BUCKET/**"
{
  echo "ObjectName,SizeBytes,Created"
  gcloud storage ls -l -r "gs://$GCS_BUCKET/**" --project "$GCP_PROJECT" 2>/dev/null \
    | awk -v b="$GCS_BUCKET" '$3 ~ /^gs:/ {gsub("gs://"b"/","",$3); print $3","$1","$2}'
} > "$EVIDENCE_DIR/upload_manifest.csv"

OBJECT_COUNT=$(($(wc -l < "$EVIDENCE_DIR/upload_manifest.csv") - 1))
{
  echo "Cloud validation"
  echo "Date: $(date)"
  echo "Bucket: <GCS_BUCKET> (name masked)"
  echo "Location: $LOCATION"
  echo "Objects in bucket: $OBJECT_COUNT"
  echo "Result: upload completed"
} > "$EVIDENCE_DIR/cloud_validation.txt"

echo "Upload complete. $OBJECT_COUNT objects in gs://$GCS_BUCKET."
echo "Evidence saved in architecture/cloud_evidence/."
