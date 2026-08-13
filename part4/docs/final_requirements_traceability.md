# Final requirements traceability — Database Systems Project Part IV

Every Part IV requirement from `ProjectPart4.pdf`, mapped to the implementation
that satisfies it, the file that holds it, the evidence that proves it, and how
that evidence was validated.

Statuses: **Complete**, **Partial**, **Not complete**, **Not applicable**.

GitHub: **not yet published.** The repository is prepared — the tree is
organised, `.gitignore` is written, and the source is scanned for credentials —
but the commit and push must be made under the author's own identity. The exact
procedure is in `part4/GITHUB_PUBLISHING.md`. Requirements D3 and D4 below are
therefore marked *Not complete*.

---

## Section 2.1 — Business use cases for a data-driven workflow application

| # | Requirement | Implementation | Code / file | Evidence | Validation | Status |
|---|---|---|---|---|---|---|
| 1.1 | Select and design business use cases | 12 use cases, UC01–UC12, refined from Part III | `part2_data_lake/workflows/quote_to_policy_use_cases.md`, report §3.2 | Use-case table in the report | Each use case exercised by the demo script | Complete |
| 1.2 | Quote and policy use case named in the assignment | Customer/agent obtains a quote, accepts it, and receives a policy | `part4/app/services/quote_service.py`, `policy_service.py` | Screenshots 2, 3, 5, 6 | `run_part4_demo.py` steps 3–10 | Complete |
| 1.3 | Products or rates updated on an ongoing basis | Regional research context and approved model themes refresh as the source and the model change | `regional_context_service.py`, `retraining_service.py` | Screenshots 4, 8, 9 | Retraining demo tests B and D | Complete |

## Section 2.2 — Documented use cases and process design

| # | Requirement | Implementation | Code / file | Evidence | Validation | Status |
|---|---|---|---|---|---|---|
| 2.1 | Document business use cases | Concise UC01–UC12 table with actor, preconditions, result, database objects, ML dependency | Report §3.2 | Report | — | Complete |
| 2.2 | Document processes with a modelling notation | Four Mermaid diagrams rendered to SVG and PNG | `part4/architecture/diagrams/part4_*.mmd/.svg/.png` | Figures 1–4 | Rendered with mermaid-cli 11.16 | Complete |
| 2.3 | Document the application design | Layered design: routes → services → ORM → PostgreSQL | Report §4, `part4/README.md` | Report | — | Complete |

## Section 2.3 — Data-driven program module

| # | Requirement | Implementation | Code / file | Evidence | Validation | Status |
|---|---|---|---|---|---|---|
| 3.1 | Leverage the Part III model | Part III `ml.src` modules reused unchanged for extraction, chunking, TF-IDF, K-means, evaluation | `part4/app/services/retraining_service.py` imports `ml.src.*` | `retraining_demonstration.txt` | Retraining demo tests B and D | Complete |
| 3.2 | Follow the documented design | Module implements the retraining sequence diagram exactly | `part4/architecture/diagrams/part4_retraining_sequence.mmd` | Figure 3 | Diagram compared against code paths | Complete |
| 3.3 | Manage the unstructured data pipeline | Resolve asset → read → hash → compare → version → extract → chunk → train → load | `source_monitor_service.py`, `retraining_service.py`, `jobs/monitor_unstructured.py` | `retraining_demonstration.txt` | 8 of 8 checks passed | Complete |
| 3.4 | Seamless retraining on source change | `monitor_unstructured --once` and `--watch` | `part4/jobs/monitor_unstructured.py` | Test B: asset v2 → ML_RUN 27 | Automatic; no manual step between detection and activation | Complete |
| 3.5 | Detect change reliably | SHA-256 over file content, compared with `DATA_ASSET.SHA256` | `source_monitor_service.sha256_of`, `check_source` | `test_source_change_detection.py` (9 tests) | `test_detection_is_not_based_on_modification_time` | Complete |
| 3.6 | Preserve previous raw versions | New bytes copied to `raw/unstructured_documents/versions/`; prior row marked Superseded, never deleted | `source_monitor_service.preserve_new_version` | Screenshot 7, `retraining_demonstration.txt` | 4 versions v1–v4 recorded with distinct checksums | Complete |
| 3.7 | Version the model | `ML_RUN.ModelVersion` bumped numerically; artifacts written per version | `retraining_service.next_model_version`, `_persist_artifacts` | `part4/model_registry/` | `test_new_runs_are_versioned_and_ordered` | Complete |
| 3.8 | Failed retraining preserves the previous model | Active model = latest **Completed** run; a failure is written as Failed | `ml_pipeline_service.active_run`, `retraining_service._mark_failed` | Test C, `test_failed_retraining_preserves_the_active_model` | ML_RUN 28 Failed, active stayed at ML_RUN 27 | Complete |
| 3.9 | No partial ML results | Chunks, assignments, summaries, and the Completed status commit in one transaction | `retraining_service.retrain` step 3 | Test C: 0 cluster rows on the failed run | `test_failed_retraining_preserves_the_active_model` | Complete |
| 3.10 | Idempotent | Second pass compares against the checksum the first pass wrote | `check_source` | Test B2 | No duplicate run created | Complete |

## Section 2.4 — Database connectivity and end-to-end application

| # | Requirement | Implementation | Code / file | Evidence | Validation | Status |
|---|---|---|---|---|---|---|
| 4.1 | Database connectivity framework | SQLAlchemy 2.0.52 Engine with a pre-pinged connection pool, psycopg 3 driver | `part4/app/db.py` | Screenshot 1 shows the live connection | `test_postgres_connection`, `test_not_sqlite` | Complete |
| 4.2 | Workflow-based application | Flask 3.1 with Jinja2, 7 pages, 14 routes | `part4/app/routes/`, `templates/` | Screenshots 1–10 | Server run and driven by Playwright | Complete |
| 4.3 | Integrate the data-driven module | ML dashboard, source check, review, and approved insight all in the application | `routes/ml_admin.py`, `regional_context.py` | Screenshots 7, 8, 9 | `run_part4_demo.py` steps 12–16 | Complete |
| 4.4 | ORM extra credit | 21 tables and 1 materialized view mapped declaratively; relationships, loader strategies, transactions | `part4/app/models/` | Report §4.2, §6 | `test_mapped_columns_match_the_database` | Complete |
| 4.5 | Transactions with rollback | `session_scope` commits on success, rolls back on any exception | `part4/app/db.py` | Report §4.4 | `test_transaction_rolls_back_on_failure`, `test_failed_conversion_leaves_no_orphan_rows` | Complete |
| 4.6 | Parameterized queries | Every ORM query binds values; raw SQL uses bound parameters | all services | `orm_sql_emitted.txt` | `test_queries_are_parameterised_not_interpolated` | Complete |
| 4.7 | Duplicate policy prevented | Row lock + service check + `UNIQUE(QuoteID)` | `policy_service.issue_policy` | Demo step 11 | `test_duplicate_conversion_is_rejected` | Complete |
| 4.8 | Error handling | Domain errors become short messages; anything else is logged and generalised | `services/errors.py`, `app/__init__.py` | `logs/part4_app.log` | Invalid transition, missing coverage, unauthorised payment all tested | Complete |

## Section 2.5 — Documentation, screenshots, and optimization

| # | Requirement | Implementation | Code / file | Evidence | Validation | Status |
|---|---|---|---|---|---|---|
| 5.1 | Document the application | Report §4, `part4/README.md`, module docstrings | — | Report | — | Complete |
| 5.2 | Explain how the solution meets the specification | This matrix plus report §9 | `part4/docs/final_requirements_traceability.md` | Report appendix | — | Complete |
| 5.3 | Screenshots that the application runs | 10 Playwright captures of the running application | `part4/evidence/screenshots/` | Figures 5–14 | Captured from `http://127.0.0.1:5055` against the live database | Complete |
| 5.4 | End-to-end: data-driven insight reaches end users | Source → model → review → mapping → quote page | Figures 1 and 4 | Screenshots 7, 8, 9 | Demo steps 12–16 | Complete |
| 5.5 | Explain query optimization | Indexes, selective materialization, measured plans | `part4/db/01_part4_extension.sql`, report §6 | `query_plans.txt`, `query_performance.csv` | EXPLAIN (ANALYZE, BUFFERS) on 8 statements | Complete |
| 5.6 | Denormalization where applicable | Part III materialized view reused as the regional read model; no new denormalized table added | `part2_data_lake/database/physical/05_materialized_views.sql` | 0.033 ms / 14 buffers vs 0.137 ms / 162 buffers | Measured, not assumed | Complete |
| 5.7 | Explain ORM optimizations | `selectinload` on the list page; measured before and after | `quote_service.list_quotes` | 26 → 2 statements, 10.73 → 1.63 ms | `test_quote_list_does_not_scale_queries_with_rows` | Complete |
| 5.8 | Report ORM risks honestly | N+1, unnecessary loading, unbounded result sets documented, including where no N+1 exists | Report §6.3 | Quote detail: 8 statements either way | `test_result_sets_are_bounded` | Complete |

## Section 2.6 — Reference architecture

| # | Requirement | Implementation | Code / file | Evidence | Validation | Status |
|---|---|---|---|---|---|---|
| 6.1 | Finalize the end-to-end RA | Four-domain diagram, implemented components only | `part4/architecture/diagrams/part4_final_reference_architecture.*` | Figure 15 | Every box maps to a running component | Complete |
| 6.2 | Business domain | Customer, agent, analyst, quote, policy, regional research, business review | RA diagram | Figure 15 | — | Complete |
| 6.3 | Application domain | Flask app, ORM, 7 services, human review, BigQuery job | RA diagram | Figure 15 | — | Complete |
| 6.4 | DIKW domain | Data → information → knowledge → decision | RA diagram | Figure 15 | — | Complete |
| 6.5 | Infrastructure domain | Data lake, PostgreSQL 16 in Docker, model registry, BigQuery Sandbox, logs, GitHub | RA diagram | Figure 15 | — | Complete |
| 6.6 | Foundational principles | 12 principles | Report §8.2 | Report | Each traced to a mechanism in code or DDL | Complete |
| 6.7 | Organizing framework | Four domains with governance spanning them | Report §8.3 | Report | — | Complete |
| 6.8 | Plan / deliver / operate method | Lifecycle described with the artifacts produced at each stage | Report §8.4 | Report | — | Complete |
| 6.9 | Governance | Quality, lifecycle, loss and leakage, ML governance, fairness, accountability, transparency | Report §8.5, `part2_data_lake/architecture/governance/` | 24 governance tests | `test_governance.py` | Complete |

## Section 4 — Deliverables

| # | Requirement | Implementation | Evidence | Status |
|---|---|---|---|---|
| D1 | One ZIP submitted to Brightspace | `part4/submission/mo_final-project_su26.zip` | ZIP integrity verified with `unzip -t` | Complete |
| D2 | Report in Microsoft Word format | `part4/report/Database_Systems_Final_Project_Report.docx` | Opens in Word; screenshots render | Complete |
| D3 | Software available through GitHub | Repository prepared: tree organised, `.gitignore` written, credential scan clean | `part4/GITHUB_PUBLISHING.md` gives the exact commands | **Not complete** — awaiting publication under the author's identity |
| D4 | GitHub link clearly indicated in the report | The report states the publication status and names the three places the URL must be inserted | Report title page, §1.1, §9.2 | **Not complete** — depends on D3 |
| D5 | Final versions of Parts I–IV | `part1/`, `part2_data_lake/` (Parts II and III), `part4/` | Directory listing under `2433-Database/` | Complete |
| D6 | Archive naming convention | `mo_final-project_su26.zip` (individual submission) | — | Complete |

## Governance and safety controls not explicitly required, but implemented

| Control | Mechanism | Validation |
|---|---|---|
| ML cannot influence price | `demonstration_premium` takes only a limit and a deductible; `quote_service` does not import `regional_context_service` | `test_ml_output_cannot_reach_the_pricing_function` |
| No patient-level data anywhere | Only county aggregates are joined; `SSN_TIN` is deliberately unmapped | `test_regional_context_carries_no_person_level_column` |
| No cardholder data | `PAYMENT_AUTHORIZATION` stores a reference only | `test_payment_stores_a_reference_only` |
| Least privilege | `part4_app_role` holds SELECT, INSERT, UPDATE; no DELETE, no DDL | `test_application_role_has_no_delete_or_ddl` |
| No credentials in version control | `.env` gitignored, `.env.example` committed, source scanned | `test_no_credentials_in_the_part4_source` |
| Append-only audit | Every transition and conversion carries an actor and a timestamp | `test_every_quote_transition_names_who_made_it` |

## Summary

| Status | Count |
|---|---|
| Complete | 46 |
| Partial | 0 |
| Not complete | 2 (D3, D4: GitHub publication) |
| Not applicable | 0 |
