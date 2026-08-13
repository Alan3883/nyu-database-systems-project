# Cloud Deployment Guide

This guide shows how to deploy the data lake and logical schema on Google Cloud. The steps use the Google Cloud CLI. The sample upload (Step 3) was executed by the student on 07/23/26. Evidence is in `cloud_evidence/`. The Cloud SQL step is optional and was not executed.

## Components

| Layer | Google Cloud service |
|-------|----------------------|
| Ingestion | Cloud Data Fusion |
| Storage (raw, processed, curated, metadata) | Cloud Storage (GCS) |
| Database (logical schema / ODS) | Cloud SQL for PostgreSQL |
| Reporting | Looker Studio |
| Governance (optional) | Dataplex Universal Catalog |

## Step 1. Install the CLI and sign in

```bash
brew install --cask google-cloud-sdk
```

```bash
gcloud auth login
```

## Step 2. Create or select a project

```bash
gcloud projects create part2-datalake-bm3883 --name="Part2 Data Lake"
gcloud config set project part2-datalake-bm3883
```

A project needs billing enabled to create buckets and databases. A personal Google account with the free trial works. Link billing in the console under Billing.

## Step 3. Create the bucket and upload samples

Use the provided script. It uploads only small sample and metadata files.

```bash
export GCP_PROJECT="part2-datalake-bm3883"
export GCS_BUCKET="part2-datalake-bm3883"
./gcloud_upload.sh
```

The folder layout in the bucket is:

```text
gs://<bucket>/metadata/
gs://<bucket>/curated/
gs://<bucket>/sample_data/
```

## Step 4. Create the PostgreSQL database

```bash
gcloud sql instances create part2-pg \
  --database-version=POSTGRES_16 \
  --tier=db-f1-micro \
  --region=us-east1 \
  --root-password="<choose-a-password>"
```

Then load the schema (from Cloud Shell or with the Cloud SQL Auth Proxy):

```bash
gcloud sql connect part2-pg --user=postgres
```

```sql
\i logical_model/logical_schema.sql
```

## Step 5. Governance controls

- Access control: use Cloud IAM roles. Give users the smallest role needed.
- Encryption: Cloud Storage and Cloud SQL encrypt data by default.
- Retention: set an Object Lifecycle Management rule on the bucket.
- Audit logs: Cloud Audit Logs record access and admin actions.
- Metadata: register the bucket in Dataplex Universal Catalog (optional).

## Notes

- Do not store keys or service-account files in the repository.
- Use `gcloud auth login` for interactive work.
- The upload script does not upload full raw datasets.
- Delete the project when done to avoid charges:

```bash
gcloud projects delete part2-datalake-bm3883
```
