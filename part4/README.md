# Part IV — End-to-end application and data-driven module

An insurance quote-to-policy application over the Part III PostgreSQL 16
database, plus a module that watches the unstructured source and retrains the
Part III model when it changes.

Part IV sits **beside** Parts II and III, not inside them:

```text
2433-Database/
├── part1/              Part I
├── part2_data_lake/    Parts II and III: the data lake, the schema, the ml package
└── part4/              this part
```

Three roots are resolved separately in `app/config.py`:

| Root | Path | What it holds |
|---|---|---|
| `CONFIG.workspace` | `2433-Database` | placed on `sys.path` so `import part4...` resolves |
| `CONFIG.part4` | `2433-Database/part4` | app, jobs, tests, model registry, evidence, logs |
| `CONFIG.lake` | `2433-Database/part2_data_lake` | the data lake and the Part III `ml` package; every `DATA_ASSET.RelativePath` is relative to this root |

`PART4_LAKE_ROOT` overrides the lake location. Part IV reads the lake and
reuses `ml.src` unchanged; it never writes into their source directories.

## Layout

```text
part4/
├── app/
│   ├── config.py            Environment-driven settings; no credential in source
│   ├── db.py                Engine, pool, session scopes, query instrumentation
│   ├── models/              SQLAlchemy mappings
│   │   ├── insurance.py     Customer, Account, Contract, health, matview
│   │   ├── quote.py         The six Part III quote-workflow tables
│   │   └── ml.py            Catalogue, ML governance, ML_CLUSTER_INDICATOR_MAP
│   ├── services/            One unit of work per function; owns the transactions
│   │   ├── quote_service.py            creation, coverage, transitions, payment
│   │   ├── policy_service.py           atomic quote-to-CONTRACT conversion
│   │   ├── regional_context_service.py county aggregates + approved themes
│   │   ├── ml_pipeline_service.py      reads: active run, clusters, versions
│   │   ├── retraining_service.py       writes: versioned, failure-safe retraining
│   │   ├── source_monitor_service.py   SHA-256 detection and raw versioning
│   │   ├── model_review_service.py     human review and indicator approval
│   │   └── errors.py                   domain exceptions
│   ├── routes/              dashboard, quotes, policies, regional_context, ml_admin
│   ├── templates/           9 Jinja2 templates
│   └── static/app.css       One local stylesheet, no CDN
├── db/
│   ├── 01_part4_extension.sql      ML_CLUSTER_INDICATOR_MAP, sequences, indexes, role
│   └── 02_part4_demo_context.sql   Demonstration service areas
├── jobs/
│   ├── monitor_unstructured.py     --once / --watch
│   └── retrain_model.py            --current / --asset-id N
├── tests/                   8 pytest suites, 96 tests, live PostgreSQL
│   └── fixtures/            make_fixtures.py builds the retraining fixtures
├── scripts/
│   ├── run_part4_database.sh        apply the Part IV DDL
│   ├── run_part4_demo.py            16-step end-to-end demonstration
│   ├── run_part4_retraining_demo.py tests A, B, B2, C, D
│   ├── measure_part4_queries.py     statement counts, timings, EXPLAIN
│   ├── capture_part4_screenshots.py Playwright capture
│   └── run_part4_cloud_analytics.sh BigQuery Sandbox
├── architecture/diagrams/   The five Part IV diagrams (mmd, svg, png)
├── model_registry/          One directory per model version
├── evidence/                Screenshots, measurements, test and retraining output
├── docs/                    Requirements traceability
├── report/  submission/     The final report and the Brightspace archive
├── GITHUB_PUBLISHING.md     The outstanding publication step
└── run.py                   Development entry point
```

The spec sketch listed `ml_pipeline_service.py` as the single ML module. It is
split here: `ml_pipeline_service` reads model state for the interface,
`retraining_service` writes it. Mixing a read helper used on every page render
with a function that opens transactions and writes model artifacts would have
made both harder to reason about.

## Running

```bash
cp part4/.env.example part4/.env   # then fill in the database password
```

Everything runs from `2433-Database/`:

```bash
bash part4/scripts/run_part4_database.sh    # apply the Part IV DDL
python3 -m part4.run                        # http://127.0.0.1:5055
python3 -m part4.jobs.monitor_unstructured --once
python3 -m part4.jobs.retrain_model --current
python3 -m pytest part4/tests -v
python3 part4/scripts/run_part4_demo.py
python3 part4/scripts/run_part4_retraining_demo.py
```

Parts II and III must already be built; see `part2_data_lake/README.md`.

## Design notes

**Active model.** There is no active flag. The active model is the `ML_RUN`
with `Status = 'Completed'` and the greatest `CompletedAt`. Everything else
follows: a failed run is written as `Failed` and can never be selected, the
previous run keeps serving with no repair step, and there is no state to
corrupt.

**Two governance gates.** A model theme becomes business insight only when
`ML_CLUSTER_SUMMARY.HumanReviewed` is TRUE *and* an `ML_CLUSTER_INDICATOR_MAP`
row is active. They are checked separately because a mapping made before review,
or left in place after a review is withdrawn, must not leak through on the
strength of the other flag.

**Pricing separation.** `demonstration_premium(coverage_limit, deductible)` has
no other parameter, and `quote_service` does not import
`regional_context_service`. The claim that model output cannot affect price is
enforced by what the code can reach, not by a policy statement.

**Session scopes.** `session_scope` commits or rolls back a unit of work.
`read_session` closes without an explicit rollback, so template attributes stay
readable after the session ends — which means a route must eagerly load
everything its template reads. That constraint is deliberate; it is also what
keeps each page's statement count bounded.
