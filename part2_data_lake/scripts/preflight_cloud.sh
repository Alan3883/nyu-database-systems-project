#!/usr/bin/env bash
# =====================================================================
# Part III cloud preflight check.
#
# Read-only. Creates nothing, uploads nothing, costs nothing.
# Tells you which of the two deployment paths your account can use.
#
# Usage:
#   bash scripts/preflight_cloud.sh
# =====================================================================

set -uo pipefail

echo "======================================================================"
echo "PART III CLOUD PREFLIGHT CHECK  (read-only, nothing is created)"
echo "======================================================================"

ok()   { echo "  [ OK ]   $*"; }
bad()  { echo "  [FAIL]   $*"; }
note() { echo "           $*"; }

# --- 1. CLI tools ----------------------------------------------------
echo ""
echo "1. Command-line tools"
if command -v gcloud >/dev/null 2>&1; then
    ok "gcloud installed: $(gcloud --version 2>/dev/null | head -1)"
else
    bad "gcloud not installed. Install with: brew install --cask google-cloud-sdk"
    exit 1
fi
if command -v bq >/dev/null 2>&1; then
    ok "bq installed: $(bq version 2>&1 | head -1)"
else
    bad "bq not installed (ships with the Google Cloud SDK)"
fi

# --- 2. Authentication -----------------------------------------------
echo ""
echo "2. Authentication"
ACTIVE=$(gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null | head -1)
if [ -n "$ACTIVE" ]; then
    ok "Active account: $ACTIVE"
    OTHERS=$(gcloud auth list --format="value(account)" 2>/dev/null | grep -v "^$ACTIVE$" || true)
    [ -n "$OTHERS" ] && note "Also authenticated: $(echo "$OTHERS" | tr '\n' ' ')"
else
    bad "No active account. Run: gcloud auth login"
    exit 1
fi

# --- 3. Project ------------------------------------------------------
echo ""
echo "3. Project"
CURRENT=$(gcloud config get-value project 2>/dev/null)
PROJECT=""
if [ -n "$CURRENT" ] && [ "$CURRENT" != "(unset)" ]; then
    STATE=$(gcloud projects describe "$CURRENT" --format="value(lifecycleState)" 2>/dev/null)
    case "$STATE" in
        ACTIVE)
            ok "Configured project is ACTIVE: $CURRENT"
            PROJECT="$CURRENT"
            ;;
        DELETE_REQUESTED)
            # GCP keeps a deleted project recoverable for 30 days.
            CREATED=$(gcloud projects describe "$CURRENT" --format="value(createTime)" 2>/dev/null)
            bad "Project '$CURRENT' is PENDING DELETION (lifecycleState=DELETE_REQUESTED)"
            note "Created: $CREATED"
            note "It can be restored within 30 days of the delete request:"
            note "    gcloud projects undelete $CURRENT"
            note "Restoring also brings back any Cloud Storage bucket it contained."
            ;;
        "")
            bad "Configured project '$CURRENT' does not exist or is not accessible"
            note "Pick another below, or create one."
            ;;
        *)
            bad "Project '$CURRENT' is in state: $STATE"
            ;;
    esac
else
    bad "No project configured"
fi

echo ""
note "Projects visible to $ACTIVE:"
gcloud projects list --format="value(projectId,name)" 2>/dev/null | sed 's/^/           - /' || note "  (none)"
COUNT=$(gcloud projects list --format="value(projectId)" 2>/dev/null | wc -l | tr -d ' ')
[ "$COUNT" = "0" ] && note "  (none — you will need to create one)"

# --- 4. Billing ------------------------------------------------------
echo ""
echo "4. Billing"
BILLING_OPEN=0
if gcloud billing accounts list >/dev/null 2>&1; then
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        ACC=$(echo "$line" | awk '{print $1}')
        OPEN=$(echo "$line" | awk '{print $NF}')
        if [ "$OPEN" = "True" ]; then
            ok "Billing account OPEN: $ACC"
            BILLING_OPEN=1
        else
            bad "Billing account CLOSED: $ACC"
        fi
    done < <(gcloud billing accounts list --format="value(name,open)" 2>/dev/null)
    [ "$BILLING_OPEN" = "0" ] && note "No open billing account found."
else
    note "Could not list billing accounts (permission or none exist)."
fi

if [ -n "$PROJECT" ]; then
    ENABLED=$(gcloud billing projects describe "$PROJECT" \
              --format="value(billingEnabled)" 2>/dev/null)
    if [ "$ENABLED" = "True" ]; then
        ok "Billing enabled on $PROJECT"
    else
        bad "Billing NOT enabled on $PROJECT"
    fi
fi

# --- 5. BigQuery reachability ---------------------------------------
echo ""
echo "5. BigQuery"
if [ -n "$PROJECT" ]; then
    if bq --project_id="$PROJECT" ls >/dev/null 2>&1; then
        ok "BigQuery reachable on $PROJECT"
        DS=$(bq --project_id="$PROJECT" ls --format=json 2>/dev/null | grep -c datasetId || echo 0)
        note "Existing datasets: $DS"
    else
        bad "BigQuery not reachable on $PROJECT"
        note "Enable it: gcloud services enable bigquery.googleapis.com --project $PROJECT"
    fi
else
    note "Skipped (no usable project)."
fi

# --- 6. Local inputs -------------------------------------------------
echo ""
echo "6. Local files the cloud step needs"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MISSING=0
for f in curated/geographic_area.csv curated/health_indicator.csv \
         curated/health_observation_sample.csv curated/data_asset.csv \
         metadata/dataset_catalog.csv ml/outputs/cluster_assignments.csv \
         ml/outputs/cluster_summary.csv; do
    if [ -f "$ROOT/$f" ]; then
        ok "$f ($(($(wc -l < "$ROOT/$f") - 1)) rows)"
    else
        bad "$f MISSING"
        MISSING=1
    fi
done
[ "$MISSING" = "1" ] && note "Rebuild with: bash scripts/run_part3_all.sh"

# --- Verdict ---------------------------------------------------------
echo ""
echo "======================================================================"
echo "RECOMMENDATION"
echo "======================================================================"
if [ "$BILLING_OPEN" = "1" ]; then
    echo "  You have an OPEN billing account."
    echo "  -> Use the FULL path (Cloud Storage + BigQuery external tables):"
    echo ""
    echo "     export GCP_PROJECT=\"<project-id>\""
    echo "     export GCS_BUCKET=\"<globally-unique-bucket-name>\""
    echo "     bash scripts/run_part3_cloud.sh --dry-run   # preview"
    echo "     bash scripts/run_part3_cloud.sh             # deploy"
else
    echo "  No OPEN billing account was found."
    echo "  Cloud Storage requires billing, but BigQuery Sandbox does not."
    echo "  -> Use the SANDBOX path (BigQuery only, free, no billing):"
    echo ""
    echo "     export GCP_PROJECT=\"<project-id>\""
    echo "     bash scripts/run_part3_cloud_sandbox.sh --dry-run   # preview"
    echo "     bash scripts/run_part3_cloud_sandbox.sh             # deploy"
    echo ""
    echo "  This still satisfies the assignment: BigQuery is the public-cloud"
    echo "  Big Data analytics service, and the data is stored and queried there."
fi
echo "======================================================================"
