# Part IV end-to-end validation

Every result below was produced by running the software against the live
PostgreSQL 16 database in the `part2-postgres` container. Commands are given so
each one can be repeated.

Environment: macOS (Darwin 25.5.0, arm64), Python 3.13.9, PostgreSQL 16.14 in
Docker, database `part3`, application on `http://127.0.0.1:5055`. Part IV lives at
`2433-Database/part4`; the data lake and the Part III `ml` package stay at
`2433-Database/part2_data_lake` and are resolved through `CONFIG.lake`.

---

## 1. Application

| Check | Command | Result |
|---|---|---|
| Server starts | `python3 -m part4.run` | Serves on 127.0.0.1:5055 |
| Dashboard loads | `GET /` | 200, quote counts, active model, source-check state |
| Quote list loads | `GET /quotes/` | 200, filterable by status |
| Quote creation | `POST /quotes/new` | Draft quote created with an opening history row |
| Coverage added | `POST /quotes/{id}/coverage` | Line stored, estimate recalculated |
| State transitions | `POST /quotes/{id}/transition` | Draft → Submitted → Rated → Presented → Accepted |
| Payment authorized | `POST /quotes/{id}/payment` | Reference stored, no cardholder data |
| Policy issued | `POST /quotes/{id}/issue` | CONTRACT + benefits + premiums + conversion in one transaction |
| Policy viewable | `GET /policies/{id}` | 200, benefits and premiums traced back to the quote |
| Regional context | quote page and `GET /regional/{account}` | County aggregates with the research-context notice |
| ML dashboard | `GET /ml/` | 200, active model, run history, preserved source versions |
| Reviewer workflow | `GET /ml/runs/{id}` and its POST actions | Review recorded, mapping approved, mapping retired |

Screenshots of each of these are in `part4/evidence/screenshots/`.

## 2. End-to-end demonstration

```bash
python3 scripts/run_part4_demo.py
```

16 of 16 steps passed. Full output in `end_to_end_demo_output.txt`. The steps
cover database availability, schema presence, quote creation, coverage,
transitions, rejection of an illegal transition, payment, acceptance, issuance,
row verification, duplicate-conversion rejection, regional context retrieval,
active-model read, approved-insight retrieval, source check, and governance.

## 3. Database

| Check | Evidence |
|---|---|
| PostgreSQL available | `SHOW server_version` → 16.14 |
| Expected tables exist | 37 base tables excluding the synthetic performance tables: 26 Part II + 6 quote workflow + 4 ML governance + 1 Part IV |
| Indexes exist | 117 indexes in `public`, including the two added by Part IV |
| Materialized view works | `MV_ACCOUNT_REGIONAL_HEALTH_PROFILE` refreshes CONCURRENTLY and serves the regional screen |
| ORM mappings match the schema | `test_mapped_columns_match_the_database` compares every mapped column against `information_schema` |
| No orphan records | `test_conversion_is_traceable_to_a_quote_and_an_actor` finds 0 conversions without a quote and 0 without a Converted history row |
| Rollback works | `test_transaction_rolls_back_on_failure` and `test_failed_conversion_leaves_no_orphan_rows` |

## 4. Machine learning and the data-driven module

```bash
python3 scripts/run_part4_retraining_demo.py
```

8 of 8 checks passed. Full output in `retraining_demonstration.txt`.

| Test | Expected | Observed |
|---|---|---|
| A — unchanged source | no retraining, no new run | `changed=False`, run count unchanged at 1 |
| B — changed source | new version, new run, results loaded, all unreviewed | asset v2 registered, ML_RUN 27 version 1.1.0, K=2, 20 chunks, 2 of 2 clusters unreviewed |
| B (versioning) | previous raw file preserved | new file written under `raw/unstructured_documents/versions/`; the original raw file is unmodified |
| B2 — repeat | no duplicate run | `changed=False`, run count unchanged |
| C — controlled failure | previous model active, failure recorded, no partial results | ML_RUN 28 marked Failed with 0 cluster rows; active model stayed at ML_RUN 27 |
| C (lineage) | the arrived bytes are still registered | asset v3 recorded even though its model was rejected |
| D — source restored | detected and retrained | ML_RUN 29 version 1.3.0 on asset v4, K=6, 32 chunks |
| D (final state) | watched file matches the registered checksum | `No change. Checksum 1d2e55927cd5bab4… matches asset version v4` |

Asset v4 and asset v1 carry the same SHA-256, which is the record that the
restore was byte-identical rather than merely similar.

## 5. Governance

| Control | Verified by |
|---|---|
| Unreviewed insight cannot appear as approved | `test_unreviewed_cluster_is_not_an_approved_insight`, `test_no_approved_insight_without_a_reviewed_cluster` |
| Reviewer name required | `test_approval_requires_a_real_reviewer_name` (7 rejected values), plus the `ck_mlcs_review` check constraint |
| Withdrawing a review withdraws the insight | `test_review_then_map_then_visible_as_approved_insight` |
| ML does not affect price | `test_ml_output_cannot_reach_the_pricing_function`, `test_quote_service_does_not_import_regional_context`, `test_regional_context_never_changes_a_premium` |
| No patient-level data | `test_regional_context_carries_no_person_level_column`, `test_customer_identifiers_are_not_mapped` |
| Least privilege | `test_application_role_has_no_delete_or_ddl` — `part4_app_role` holds SELECT, INSERT, UPDATE only |
| No credentials committed | `test_no_credentials_in_the_part4_source`, `test_env_file_is_ignored_by_git` |
| Every transition attributable | `test_every_quote_transition_names_who_made_it` — 0 rows with a blank actor |

## 6. Tests

```bash
python3 -m pytest part4/tests -v
```

96 passed, 0 failed. Full output in `application_test_results.txt`.

| Suite | Tests | Covers |
|---|---|---|
| `test_database_integration.py` | 12 | connectivity, mapping fidelity, transactions, constraints, pooling |
| `test_quote_workflow.py` | 15 | creation, validation, coverage, transitions, payment |
| `test_policy_conversion.py` | 10 | atomic issuance, completeness, duplicate prevention, rollback |
| `test_ml_integration.py` | 10 | active run, review gate, approved insight, pricing separation |
| `test_source_change_detection.py` | 9 | checksum detection, mtime independence, version integrity |
| `test_model_retraining.py` | 7 | versioning, failure path, registry, governance reset |
| `test_governance.py` | 24 | review, accountability, privacy, least privilege, secrets |
| `test_query_behavior.py` | 9 | statement counts, loader strategies, bounded result sets |

## 7. Query and ORM measurements

```bash
python3 scripts/measure_part4_queries.py
```

Results in `query_performance.csv`, emitted SQL in `orm_sql_emitted.txt`, plans
in `query_plans.txt`. Median of seven runs.

| Path | Statements | Wall ms |
|---|---|---|
| Dashboard | 7 | 6.63 |
| Quote list, lazy loading | 26 | 10.83 |
| Quote list, `selectinload` | **2** | **1.62** |
| Quote detail, lazy loading | 8 | 3.36 |
| Quote detail, `selectinload` | 8 | 4.17 |
| Policy detail | 6 | 2.98 |
| Regional context via the materialized view | 2 | 1.55 |
| Regional context via the five-table join | 1 | 1.28 |

Two honest readings of this table:

* The quote list is a genuine N+1. Twenty-five rows each printing a customer
  name produced 26 statements; `selectinload` reduced that to 2 and cut wall
  time by 85%.
* The quote detail page is **not** an N+1. It reads seven relationships of one
  quote, so lazy loading and `selectinload` issue the same eight statements and
  the eager version is marginally slower here. Eager loading is kept because it
  bounds the count as the aggregate grows, not because it is faster today.

At the database level the materialized view is the clear win, even though the
Python-side wall time above does not show it — the view path includes a second
statement for approved themes:

| Read | Execution time | Buffers |
|---|---|---|
| `MV_ACCOUNT_REGIONAL_HEALTH_PROFILE` | 0.035 ms | 16 shared hits |
| Equivalent five-table join | 0.130 ms | 210 shared hits |

Roughly 4x faster and 13x fewer buffer reads for the same 15 rows. The view is scanned
sequentially rather than through `ix_mv_arhp_account` because it holds only 349
rows; the planner is right to skip the index at that size.

## 8. Cloud analytics

```bash
bash scripts/run_part4_cloud_analytics.sh
```

Output in `cloud/part4_cloud_output.txt`. The Part IV job exports the model-run
register and the approved-insight mappings to BigQuery Sandbox and runs four
queries over them joined to the Part III public-health tables. No customer,
quote, contract, or payment row is exported.

## 9. Known gaps

* The regional screen is limited by the 320-row curated observation sample.
* Insurance rows are synthetic demonstration data; the public health data is real.
* The application has no authentication layer, so reviewer and actor names are
  recorded but not authenticated.
