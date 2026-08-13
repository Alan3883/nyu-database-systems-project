# Screenshot Checklist

Visual evidence to capture from the Google Cloud console after running
`scripts/run_part3_cloud.sh`. Screenshots supplement, but do not replace, the generated
evidence files.

**Before capturing:** confirm no billing account number, no service-account key, and no
personal email is visible. Crop or blur if needed.

| # | Screen | Path | What must be visible |
|---|--------|------|----------------------|
| 1 | Bucket overview | Cloud Storage → Buckets | Bucket name, location, uniform access enabled, **public access: not public** |
| 2 | part3 prefix | Cloud Storage → bucket → part3/ | Subfolders: curated, metadata, ml, database, architecture |
| 3 | Part II preserved | Cloud Storage → bucket root | Part II prefixes still present alongside part3/ (only if reusing the Part II bucket) |
| 4 | ML outputs | Cloud Storage → part3/ml/outputs/ | The CSV files and two PNG visualizations |
| 5 | BigQuery dataset | BigQuery → Explorer | Dataset `part3_analytics` with 7 tables |
| 6 | Table schema | BigQuery → health_observation → Schema | Column names and types |
| 7 | Query 1 result | BigQuery → Results | Geography-level counts: 1 Nation, 51 State, 3,144 County |
| 8 | Query 2 result | BigQuery → Results | State-level indicator averages |
| 9 | Query 3 result | BigQuery → Results | 6 clusters with chunk counts and HumanReviewed = FALSE |
| 10 | Job history | BigQuery → Job history | Query jobs with bytes processed and duration |
| 11 | IAM | IAM & Admin → IAM | Principals and roles, demonstrating least privilege |
| 12 | Billing | Billing → Reports | Cost for the period, confirming the free tier was not exceeded |

## Cross-check against generated evidence

| Screenshot | Should match |
|------------|--------------|
| 5, 6 | `object_inventory.csv` |
| 7, 8, 9 | `analytics_results.csv` |
| 1, 2 | `resource_inventory.md` |

If a screenshot disagrees with a generated file, the generated file is authoritative; rerun
the script and recapture.
