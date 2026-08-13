# How to Complete the Cloud Big Data Analytics Requirement (R3.5)

This is the only outstanding Part III requirement. Everything is scripted; you just need to
run it against a project you control.

Run the diagnostic first — it is read-only and costs nothing:

```bash
bash scripts/preflight_cloud.sh
```

---

## What the diagnostic found on 08/06/26

| Finding | Detail |
|---------|--------|
| gcloud + bq installed | Yes, SDK 577.0.0 |
| Authenticated | `alanmob20@gmail.com` (active), `bm3883@nyu.edu` |
| Part II project `part2-datalake-bm3883` | **PENDING DELETION** — recoverable until about 08/22/26 |
| Visible active projects | None |
| Billing accounts | Two, **both CLOSED** |
| Local input files | All 7 present |

Two consequences:

1. **Cloud Storage will not work without an open billing account.** GCS always requires
   billing, even inside the free tier.
2. **BigQuery Sandbox works without billing.** It gives 10 GB storage and 1 TB of query
   processing per month, free, with no billing account attached.

Since the assignment asks you to *"leverage Big Data Analytics ... available via platform
services provided on the big public clouds to extract, filter, store, analyze your datasets
and present your analytics results"*, BigQuery alone satisfies it. Cloud Storage is a
convenience, not the requirement.

---

## Path A — BigQuery Sandbox (recommended, free, ~5 minutes)

No billing account, no credit card. This is the fastest way to close R3.5.

### A1. Create a project

```bash
gcloud projects create part3-bq-bm3883 --name="Part3 BigQuery"
```

If that ID is taken, add digits. Then set it as default:

```bash
gcloud config set project part3-bq-bm3883
```

### A2. Enable the BigQuery API

```bash
gcloud services enable bigquery.googleapis.com --project part3-bq-bm3883
```

If this fails saying billing is required, open
https://console.cloud.google.com/bigquery, select the project, and click through the
**Sandbox** prompt once. That activates sandbox mode without billing.

### A3. Preview, then run

```bash
export GCP_PROJECT="part3-bq-bm3883" && bash scripts/run_part3_cloud_sandbox.sh --dry-run
```

The dry run creates nothing. When the plan looks right:

```bash
export GCP_PROJECT="part3-bq-bm3883" && bash scripts/run_part3_cloud_sandbox.sh
```

### A4. What it does

| Step | Action |
|------|--------|
| 1 | Creates BigQuery dataset `part3_analytics` |
| 2 | Loads 7 tables straight from local CSV (3,196 + 148 + 320 + 10 + 10 + 32 + 6 rows) |
| 3 | Writes `object_inventory.csv` with row counts |
| 4 | Runs 4 analytical queries and writes `analytics_results.csv` |
| 5 | Writes `resource_inventory.md` |

All output lands in `architecture/cloud_evidence/part3/`, with the project name masked.

### A5. Expected row counts

| Table | Rows |
|-------|------|
| geographic_area | 3,196 |
| health_indicator | 148 |
| health_observation | 320 |
| dataset_catalog | 10 |
| data_asset | 10 |
| ml_cluster_assignments | 32 |
| ml_cluster_summary | 6 |

If any table shows 0 or `error`, tell me the message rather than rerunning blindly.

---

## Path B — Full path with Cloud Storage (needs an open billing account)

Only worth doing if you want the GCS `part3/` prefix as well as BigQuery.

### B1. Reopen billing

Go to https://console.cloud.google.com/billing. Both existing accounts show as closed. Either
reopen one, or create a new one. A new Google Cloud account normally includes a $300 / 90-day
free trial; your card is not charged unless you explicitly upgrade.

### B2. Optionally restore the Part II project

Your Part II project is still recoverable, which would bring back the bucket holding the 23
Part II objects:

```bash
gcloud projects undelete part2-datalake-bm3883
```

**This is time-limited: it disappears permanently around 08/22/26.** Restoring is worthwhile
for continuity, because the Part II report describes those 23 objects. It is not required for
Part III to be complete — the Part II evidence files in the repository are the graded record.

### B3. Link billing and enable APIs

```bash
gcloud config set project part3-datalake-bm3883
```

```bash
gcloud services enable bigquery.googleapis.com storage.googleapis.com
```

### B4. Preview, then run

```bash
export GCP_PROJECT="part3-datalake-bm3883" && export GCS_BUCKET="part3-datalake-bm3883" && bash scripts/run_part3_cloud.sh --dry-run
```

```bash
export GCP_PROJECT="part3-datalake-bm3883" && export GCS_BUCKET="part3-datalake-bm3883" && bash scripts/run_part3_cloud.sh
```

Bucket names are globally unique. If creation fails with "already exists", pick another.

### B5. What differs from Path A

| | Path A (Sandbox) | Path B (Full) |
|---|---|---|
| Billing needed | No | Yes |
| Cloud Storage `part3/` prefix | Not used | Yes |
| BigQuery tables | Loaded from local files | External tables reading GCS |
| Analytical queries | Same 4 | Same 4 |
| Evidence files produced | Same | Same, plus GCS object listing |
| Satisfies R3.5 | Yes | Yes |

---

## After either path completes

Tell me it is done. I will then:

1. Read the generated evidence files.
2. Update the report Section 26 from "not executed" to the actual results.
3. Flip R3.5 in `docs/requirements_traceability_matrix.md` from **Not completed** to
   **Complete**, and R2.1h from Partially complete.
4. Update `docs/limitations.md` and the execution log.
5. Rerun validation and repackage `Mo_p3_su26.zip`.

`validate_part3.py` currently blocks the report from claiming cloud execution while
`architecture/cloud_evidence/part3/` holds no results file, so this cannot be faked by
accident.

Optionally capture the screenshots listed in
`architecture/cloud_evidence/part3/screenshot_checklist.md` for visual evidence.

---

## Cleaning up afterwards

Sandbox tables expire on their own after 60 days and cost nothing. If you want to remove
everything immediately:

```bash
bq rm -r -f --dataset part3-bq-bm3883:part3_analytics
```

**Do not delete the whole project this time until after grading.** Deleting the Part II
project is what removed its bucket and the 23 objects the Part II report describes.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `BigQuery API has not been enabled` | API off for the project | `gcloud services enable bigquery.googleapis.com` |
| `billing account ... is not open` | Closed billing | Use Path A, or reopen billing |
| `Not found: Dataset` on a query | Load step failed earlier | Check the load output in `sanitized_command_output.txt` |
| `Bucket already exists` | Names are global | Choose a different bucket name |
| `Access Denied: Project` | Wrong active account | `gcloud config set account alanmob20@gmail.com` |
| Query returns 0 rows | Autodetect typed a join key oddly | Already handled: every join casts to STRING |
| `Permission denied` on the script | Not executable | `chmod +x scripts/run_part3_cloud_sandbox.sh` |
