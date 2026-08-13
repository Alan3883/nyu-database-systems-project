# NYU CSCI-GA.2433-001 Database Systems — Course Project

Alan Mo (bm3883). An insurance enterprise data architecture built across four
milestones: a conceptual model, a hybrid logical schema and data lake, an
optimized physical database with a machine-learning model over unstructured
data, and — in Part IV — a working end-to-end application that ties all of it
together.

| Part | Deliverable | Status |
|------|-------------|--------|
| I | Conceptual ER model, 20 entities in 4 subject areas | Submitted |
| II | Logical schema (26 tables), 4-zone data lake, 10 public datasets | Submitted |
| III | Physical design, quote workflow, TF-IDF + K-means model, cloud analytics | Submitted |
| IV | End-to-end application, ORM, source monitoring, failure-safe retraining | This submission |

## What Part IV adds

A Flask + SQLAlchemy application over the existing PostgreSQL 16 database, plus
a data-driven module that watches the unstructured source and retrains the
model when it changes.

* **Quote to policy.** Create a quote, add coverage, move it through
  Draft → Submitted → Rated → Presented → Accepted, authorize payment, and
  issue a policy. Issuance writes CONTRACT, CONTRACT_BENEFIT, CONTRACT_PREMIUM,
  QUOTE_CONVERSION, the quote status, and its history row in one transaction.
  `UNIQUE(QuoteID)` on QUOTE_CONVERSION makes a second policy impossible.
* **Source monitoring.** SHA-256 comparison against `DATA_ASSET.SHA256`, not
  modification time. An unchanged source produces no model run.
* **Failure-safe retraining.** A changed source is preserved as a new immutable
  raw version, then the Part III pipeline retrains. The active model is defined
  as the completed run with the latest completion time, so a failed run is
  recorded and simply never becomes active.
* **Governed ML integration.** A cluster becomes business insight only after a
  named analyst reviews it *and* an active `ML_CLUSTER_INDICATOR_MAP` row links
  it to an existing HEALTH_INDICATOR. Two independent gates.
* **Regional research context.** County-level public health aggregates shown on
  the quote page, labelled *research context — not a rating input*. The pricing
  function takes a coverage limit and a deductible and nothing else.

## Architecture

![Final reference architecture](../part4/architecture/diagrams/part4_final_reference_architecture.png)

Process diagrams: [end-to-end workflow](../part4/architecture/diagrams/part4_end_to_end_workflow.png) ·
[quote-to-policy sequence](../part4/architecture/diagrams/part4_quote_to_policy_sequence.png) ·
[retraining sequence](../part4/architecture/diagrams/part4_retraining_sequence.png) ·
[ML-to-ODS integration](../part4/architecture/diagrams/part4_ml_to_ods_integration.png)

## Repository layout

This directory is named `part2_data_lake` for historical reasons: it began as
the Part II data lake and Part III was built inside it. Part I and Part IV live
beside it under `2433-Database/`.

```text
2433-Database/
├── part1/              Part I conceptual model and report
├── part2_data_lake/    this directory: Parts II and III
└── part4/              Part IV application, jobs, tests, report, evidence
```

Inside this directory:

```text
raw/ processed/ curated/ metadata/   Part II four-zone data lake
logical_model/               Part II logical schema and diagrams
database/                    Part III physical design
  physical/                  DDL: schema, indexes, workflow, ML metadata, views, roles
  queries/                   Workload queries, EXPLAIN, BigQuery analytics
  tests/                     Constraint tests and pytest suite
  evidence/                  Part III performance results
ml/                          Part III ML pipeline, trained model, outputs, tests
architecture/                Part II and III diagrams, governance, cloud evidence
workflows/                   Quote-to-contract use cases
docs/                        Design decisions, limitations
report/                      Part II and Part III reports
scripts/                     Part II and III pipeline scripts
```

Part IV lives in `../part4`. It reads this directory as its data lake and
imports the `ml` package from it, but it writes only inside its own tree.

## Requirements

* Python 3.11 or newer (developed on 3.13)
* Docker, for PostgreSQL 16
* `bq` and `gcloud`, only for the optional BigQuery step
* Node, only to regenerate diagrams with mermaid-cli

```bash
python3 -m pip install -r scripts/requirements.txt
```

## Setup

### 1. Start PostgreSQL

```bash
docker run -d --name part2-postgres -e POSTGRES_PASSWORD=<your-password> -p 5432:5432 postgres:16
```

### 2. Configure credentials

No credential is stored in this repository. Copy the template and fill it in:

```bash
cp ../part4/.env.example ../part4/.env
```

`part4/.env` is excluded by `.gitignore`.

### 3. Restore the raw data (only if rebuilding from scratch)

`raw/`, `processed/`, and `sample_data/` are excluded from version control:
264 MB of public downloads that can be fetched again from their sources.

```bash
python3 scripts/download_part2_data.py
python3 scripts/01_inventory_data.py
python3 scripts/02_profile_data.py
python3 scripts/03_build_curated_data.py
```

The DS010 report PDF (14 MB, County Health Rankings & Roadmaps 2025 national
report) is downloaded by the same script; `metadata/download_manifest.json`
records the URL and the expected SHA-256 so the restored file can be verified.

### 4. Build the database

```bash
bash scripts/run_part3_database.sh              # Part II schema + Part III physical layer
bash ../part4/scripts/run_part4_database.sh     # Part IV extension
```

### 5. Train the Part III model (optional; the database ships with a run)

```bash
python3 -m ml.src.run_pipeline
python3 scripts/load_ml_results_to_postgres.py
```

## Running

### Application

Run from `2433-Database/`, not from this directory:

```bash
cd .. && python3 -m part4.run
```

Then open <http://127.0.0.1:5055>.

### Source monitor

```bash
python3 -m part4.jobs.monitor_unstructured --once
python3 -m part4.jobs.monitor_unstructured --watch --interval 300
```

### Manual retraining

```bash
python3 -m part4.jobs.retrain_model --current
```

### Tests

```bash
cd .. && python3 -m pytest part4/tests -v   # Part IV: 8 suites, 96 tests
python3 -m pytest ml/tests -v         # Part III ML pipeline
python3 -m pytest database/tests -v   # Part III database
```

### Demonstrations

From `2433-Database/`:

```bash
python3 part4/scripts/run_part4_demo.py             # 16-step quote-to-policy walkthrough
python3 part4/scripts/run_part4_retraining_demo.py  # retraining tests A, B, B2, C, D
python3 part4/scripts/measure_part4_queries.py      # query and ORM measurements
python3 part4/scripts/capture_part4_screenshots.py  # Playwright screenshots (app must be running)
```

### Cloud analytics

BigQuery Sandbox only: no billing account, no Cloud Storage bucket, no
service-account key. The script exports model-governance metadata and aggregate
public-health data. No customer, quote, contract, or payment row is ever sent
to the cloud.

```bash
bash ../part4/scripts/run_part4_cloud_analytics.sh
```

## Limitations

* The demonstration premium is `limit/1000 × 4.25 − deductible × 0.05`. It is a
  placeholder for a rating engine, not a filed insurance rate.
* HEALTH_OBSERVATION holds a 320-row sample of the public data, so a county
  carries at most three observations. `part4/db/02_part4_demo_context.sql` gives
  ten demonstration accounts several service areas so the regional screen has
  enough rows to be legible; no observation value is invented.
* Customer, account, and contract rows are synthetic demonstration data
  generated by `scripts/load_curated_to_postgres.py`. The public health data is
  real.
* The application runs on Flask's development server on localhost. There is no
  authentication layer; the reviewer and actor names typed into forms are
  recorded for audit but are not authenticated identities.
* The 500,000-row partitioned table from Part III exists for performance
  measurement and is not read by the application.
