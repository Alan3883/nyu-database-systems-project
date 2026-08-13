# Part III Cloud Deployment Commands

Every command needed, with an explanation of what it does and why.
Project and bucket names below are examples; substitute your own.

## 1. Authenticate

```bash
gcloud auth login
```

Opens a browser for Google sign-in. A personal Google account with the free trial works.
The NYU account could not create a billable project, which is why Part II used a personal
account.

## 2. Create a project and enable billing

```bash
gcloud projects create part3-datalake-bm3883 --name="Part3 Data Lake"
gcloud config set project part3-datalake-bm3883
```

Billing must then be linked in the console at https://console.cloud.google.com/billing.
BigQuery will not run a query on a project without billing, even inside the free tier.

## 3. Enable the BigQuery API

```bash
gcloud services enable bigquery.googleapis.com --project part3-datalake-bm3883
```

Only needed once per project.

## 4. Run the deployment

```bash
export GCP_PROJECT="part3-datalake-bm3883"
export GCS_BUCKET="part3-datalake-bm3883"
bash scripts/run_part3_cloud.sh
```

The script performs five steps:

| Step | Action |
|------|--------|
| 1 | Create the bucket if absent; report existing object count if present |
| 2 | Upload Part III outputs under the `part3/` prefix only |
| 3 | Create a BigQuery dataset **in the bucket's location**, read at run time |
| 4 | Create 7 external tables and run 3 analytical queries |
| 5 | Write the resource inventory |

Bucket names are globally unique. If creation fails with "already exists", choose another
name.

## 5. Verify

```bash
gcloud storage ls -r "gs://$GCS_BUCKET/part3/**" | head -20
bq ls part3_analytics
bq query --use_legacy_sql=false \
  "SELECT COUNT(*) FROM \`$GCP_PROJECT.part3_analytics.health_observation\`"
```

Expected: 320 rows in `health_observation`, 3,196 in `geographic_area`, 148 in
`health_indicator`, 32 in `ml_cluster_assignments`, 6 in `ml_cluster_summary`.

## 6. Clean up after grading

```bash
gcloud projects delete part3-datalake-bm3883
```

Deletes every resource in the project and stops all charges. Note this is what removed the
Part II bucket; if the Part II deployment needs to remain inspectable, keep the project and
delete only the bucket instead:

```bash
gcloud storage rm -r "gs://$GCS_BUCKET"
```

## Why these services and not others

| Service | Decision | Reason |
|---------|----------|--------|
| Cloud Storage | **Deployed** | The lake zones map directly onto prefixes |
| BigQuery | **Deployed** | Serverless SQL analytics; no cluster to manage; free tier covers this volume |
| Cloud SQL | Not deployed | The local PostgreSQL 16 container is the operational database; a managed instance adds cost without adding capability at this scale |
| Cloud Data Fusion | Not deployed | Minimum cost is far above what five Python scripts justify |
| Dataplex | Not deployed | The metadata layer is already file-based and versioned in the repository |
| Vertex AI | Not deployed | The model trains locally in about 3 seconds |
| Pub/Sub + Dataflow | Not deployed | The sources publish annually; there is no streaming requirement |

All of the "not deployed" services appear in the future-state architecture, clearly marked
as planned.
