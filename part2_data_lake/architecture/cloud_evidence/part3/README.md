# Part III Cloud Evidence

## Status: PREPARED, NOT YET EXECUTED

The deployment script is complete and syntax-checked. It has **not been run**, so this
folder does not yet contain `object_inventory.csv`, `analytics_results.csv`, or
`sanitized_command_output.txt`. Those files are produced only by a real run.

**No cloud result is claimed anywhere in this project that is not backed by a file in this
folder.** The Part III report states the cloud requirement as deployment-ready rather than
complete.

## Why it has not been run

The Part II GCP project `part2-datalake-bm3883` was deleted after Part II was submitted, to
avoid ongoing charges. Verified on 08/05/26:

```
$ gcloud storage ls --project part2-datalake-bm3883
ERROR: HTTPError 404: The requested project was not found.
```

The Part II bucket and its 23 objects therefore no longer exist. The Part II evidence files
in `architecture/cloud_evidence/` (one level up) are retained unchanged as the historical
record of that deployment.

Running Part III needs a project with billing enabled and the owner's credentials, so it is
executed by the student rather than automatically.

## How to run it

Start with the read-only diagnostic, which reports which path your account can use:

```bash
bash scripts/preflight_cloud.sh
```

Two paths exist. Full instructions are in `docs/CLOUD_HOWTO.md`.

**Path A - BigQuery Sandbox (no billing account required).** Loads the curated and ML tables
directly into BigQuery from local files and runs the analytical queries. Cloud Storage is
skipped because it requires billing.

```bash
export GCP_PROJECT="<project-id>"
bash scripts/run_part3_cloud_sandbox.sh --dry-run   # preview, creates nothing
bash scripts/run_part3_cloud_sandbox.sh             # deploy
```

**Path B - full path (requires an open billing account).** Adds the Cloud Storage `part3/`
prefix and uses BigQuery external tables over it.

```bash
export GCP_PROJECT="<project-id>"
export GCS_BUCKET="<globally-unique-name>"
bash scripts/run_part3_cloud.sh --dry-run
bash scripts/run_part3_cloud.sh
```

Both scripts only ever write under the `part3/` prefix and never modify objects already
present.

## Account state recorded on 08/06/26

| Check | Result |
|-------|--------|
| gcloud and bq installed | Yes |
| Authenticated accounts | alanmob20@gmail.com (active), bm3883@nyu.edu |
| Billing accounts | Two, both CLOSED |
| Part II project `part2-datalake-bm3883` | lifecycleState DELETE_REQUESTED, recoverable until about 08/22/26 via `gcloud projects undelete` |

Because no billing account is open, Path A is the applicable route.

## What the run produces

| File | Content |
|------|---------|
| `resource_inventory.md` | Deployed resources with locations and object counts |
| `object_inventory.csv` | BigQuery table names with row counts |
| `analytics_results.csv` | Results of the three analytical queries |
| `sanitized_command_output.txt` | Full command log, project and bucket names masked |

Identifiers are masked as the log is written, so no secret is stored.

## Files already in this folder

| File | Purpose |
|------|---------|
| `README.md` | This file |
| `deployment_commands.md` | Exact commands with explanations |
| `analytics_queries.sql` | The three required queries, ready to paste |
| `screenshot_checklist.md` | What to capture from the console as visual evidence |

## Cleanup after grading

```bash
gcloud projects delete part3-datalake-bm3883
```
