# Requirements Traceability Matrix

Maps every Project Part III requirement to its implementation, file path, verification method,
and status.

**Status definitions**

| Status | Meaning |
|--------|---------|
| Complete | Implemented and verified by an executed command producing evidence on disk |
| Partially complete | Implemented, but some element is unverified or deferred |
| Not completed | Not implemented |
| Not applicable | Out of scope for this project |

A deployment script alone does not make a cloud requirement complete. A diagram alone does not
make an implementation complete.

---

## Section 2: EDA Physical Database Design

| ID | Assignment wording | Implementation | File path | Verification | Status | Limitation |
|----|--------------------|----------------|-----------|--------------|--------|------------|
| R2.1a | "Perform and document physical database design" | Physical layer applied on top of the Part II logical schema: types, audit columns, fillfactor, statistics targets | `database/physical/01_physical_schema.sql` | Applied to PostgreSQL 16; 78 pytest checks | **Complete** | — |
| R2.1b | "...may include **indexing**" | 16 new workload-driven indexes (composite, partial, covering) on top of the 52 inherited from Part II, giving 87 in total. Each documented with table, columns, order, query served, benefit, write cost, reason | `database/physical/02_indexes.sql` | `EXPLAIN (ANALYZE, BUFFERS)`; 222x gain measured at 500k rows | **Complete** | At 50–320 row sample sizes the planner correctly prefers sequential scans; recorded honestly |
| R2.1c | "...**partitioning**" | Evaluated and measured on a 500k synthetic table with 10 yearly RANGE partitions. **Not applied** to live tables | `database/physical/07_partitioning_and_clustering.sql` | Pruning verified: 1 of 10 partitions scanned; 417 vs 4,167 buffers on scans | **Complete** (as an evaluation with a documented decision) | Live `HEALTH_OBSERVATION` holds 320 rows, so partitioning is not justified yet |
| R2.1d | "...**clustering**" | `CLUSTER` evaluated and executed on the synthetic table; rejected for all update-heavy tables with reasons | `database/physical/07_partitioning_and_clustering.sql` | Executed successfully | **Complete** | One-time reorganisation; PostgreSQL does not maintain the order |
| R2.1e | "...**selective materialization**" | `MV_ACCOUNT_REGIONAL_HEALTH_PROFILE` over the five-table hybrid path, with 4 indexes, refresh strategy, and a validation view | `database/physical/05_materialized_views.sql` | 0.027 ms vs 0.072 ms for the live join (2.7x); `V_MV_ARHP_VALIDATION` reports IN SYNC | **Complete** | — |
| R2.1f | "Please explain all choices being made" | Every index carries a Query/Benefit/Cost/Reason comment block; every technique has a documented decision | `database/physical/*.sql`, `database/evidence/query_plan_summary.md` | Manual review | **Complete** | — |
| R2.1g | "deploy your resulting design on a mainstream relational database system" | PostgreSQL 16.14 in Docker; 36 tables, 48 FKs, 38 check constraints, 87 indexes, 1 materialized view | `scripts/run_part3_database.sh` | Full rebuild from scratch succeeds | **Complete** | — |
| R2.1h | "preferably on one of the big clouds... fine to combine local and cloud" | Local PostgreSQL 16 is the operational database; Google BigQuery is the cloud analytics layer holding 7 loaded tables | `scripts/run_part3_cloud_sandbox.sh` | Executed 08/06/26; `object_inventory.csv` shows 7 tables with row counts matching local sources | **Complete** | Cloud Storage not used; it requires a billing account and none was open |
| R2.2a | "Identify appropriate business use cases... quote and a policy" | 16 use cases with actor, trigger, preconditions, main/alternate/exception flows, data read/created/updated, postconditions, security and audit controls | `workflows/quote_to_policy_use_cases.md` | Peer-readable; mapped to tables | **Complete** | — |
| R2.2b | "Document... the processes used by your application using a modeling notation" | Mermaid activity-style flowchart and sequence diagram, both rendered to SVG and PNG | `workflows/quote_to_policy_workflow.{mmd,svg,png}`, `quote_to_policy_sequence.{mmd,svg,png}` | Rendered with mermaid-cli; visually inspected | **Complete** | — |
| R2.2c | "You do not need to implement a database program at this stage" | No application code written. Six supporting tables created and constraint-tested | `database/physical/03_workflow_extension.sql` | 9 negative tests fired correctly | **Complete** | Intentionally no application layer |

## Section 3: Machine Learning Model Creation

| ID | Assignment wording | Implementation | File path | Verification | Status | Limitation |
|----|--------------------|----------------|-----------|--------------|--------|------------|
| R3.1a | "Refine and complement the use cases identified in the second part" | Part II regional-context use case extended into the quote workflow (UC-07) and into ML-driven theme discovery | `workflows/quote_to_policy_use_cases.md`, `ml/outputs/business_insights.md` | Documented | **Complete** | — |
| R3.1b | "establish your approach to evaluate Big Data ideas... short, medium, and long term benefits" | Evaluation framework with four criteria (data availability, effort, fairness risk, validatability) and a three-horizon table | `ml/outputs/business_insights.md` § "Evaluating Big Data ideas" | Documented; each idea marked implemented or not | **Complete** | Only short-term items were implemented; medium and long term are explicitly not built |
| R3.2a | "Select and train machine learning algorithm(s)" | TF-IDF + K-means (unsupervised) over DS010. Model selection across K=2..8 using silhouette, Davies-Bouldin, Calinski-Harabasz, with a minimum-cluster-size constraint | `ml/src/train_cluster_model.py` | Pipeline executed; 44 pytest checks; reproducible byte-for-byte | **Complete** | Silhouette 0.1212 is weak; reported as such |
| R3.2b | "to extract insights to help drive business decisions" | Six themes with top terms, representative passages, business use, required review, and limitations | `ml/outputs/business_insights.md` | Model output inspected against source pages | **Complete** | All six clusters are `HumanReviewed = FALSE`; insights are candidate findings |
| R3.2c | Section 3 heading: "analytics on the **unstructured data** collected in the second part" | DS010 PDF (18 pages) is the sole training asset | `raw/unstructured_documents/chr_2025_national_report.pdf` | SHA-256 verified against the download manifest | **Complete** | One document only |
| R3.3a | "Keep developing your Big Data platform and data lake" | Four zones retained; `sample_data/` and Part III ML outputs added; 10 datasets catalogued with licences | `metadata/`, `curated/`, `ml/outputs/` | `04_validate_outputs.py`: 14 checks pass | **Complete** | — |
| R3.3b | "further identify how insights... will feed into the EDA" | Five-step feedback path from cluster to `HEALTH_INDICATOR`/`HEALTH_OBSERVATION` to `ACCOUNT_GEOGRAPHY` to a quote risk factor, gated by human review | `ml/outputs/business_insights.md` § "How insights feed back into the EDA" | Path enforced by `ck_qrf_source` | **Complete** | — |
| R3.3c | "designed with growth in mind" | Catalogue-driven dataset addition; `DOCUMENT_CHUNK` supports many assets; partitioning design proven at 500k rows; `ML_RUN` versioning | `architecture/governance/data_governance.md` § 8 | Growth table documented | **Complete** | — |
| R3.3d | "continually improve data analytics and **visualization** capabilities" | Two matplotlib figures: TruncatedSVD cluster scatter annotated with source pages, and per-cluster top-term bar charts | `ml/outputs/cluster_visualization.png`, `top_terms_by_cluster.png` | Generated by the pipeline | **Complete** | Static images; interactive dashboards are future-state |
| R3.4 | "Elaborate further on the reference architecture" | Two separated views: implemented (only real components) and future-state (labelled planned), spanning business, application, DIKW, and infrastructure | `architecture/diagrams/part3_reference_architecture.mmd`, `part3_future_state_architecture.mmd` | Rendered to SVG | **Complete** | — |
| R3.5 | "Leverage Big Data Analytics... on the big public clouds to extract, filter, store, analyze... and present your analytics results" | BigQuery dataset `part3_analytics` with 7 loaded tables and 4 executed analytical queries covering geography counts, state-level indicator summaries, ML cluster summaries, and dataset lineage | `scripts/run_part3_cloud_sandbox.sh`, `database/queries/bigquery_analytics.sql` | **Executed 08/06/26.** Evidence: `object_inventory.csv` (7 tables, counts verified), `analytics_results.csv` (4 query results), `resource_inventory.md`, `sanitized_command_output.txt` | **Complete** | Ran in BigQuery Sandbox, so Cloud Storage was not used and tables expire after 60 days |

## Section 1 implicit requirements

| ID | Assignment wording | Implementation | File path | Verification | Status |
|----|--------------------|----------------|-----------|--------------|--------|
| R1.1 | Architecture spans "business, application, pyramid of knowledge (DIKW), and infrastructure domains" | All four domains modelled as labelled subgraphs, with the DIKW pyramid mapped to concrete project artefacts | `architecture/diagrams/part3_reference_architecture.mmd` | Rendered | **Complete** |
| R1.2 | "metadata management, data quality, and data governance/intelligence" | Five governance documents plus four machine-readable metadata artefacts | `architecture/governance/*.md`, `metadata/*` | Documented and measured | **Complete** |
| R1.3 | Prevent "data swamps" | Four controls: catalogue entry required, checksums on every file, lineage on every derived artefact, defined zone semantics | `architecture/governance/data_governance.md` § 7 | 10/10 checksums verified | **Complete** |
| R1.4 | "secure their cloud and prevent data loss and leakage" | Credential scanning, four least-privilege roles, column-level revoke on SSN_TIN, private bucket, masked evidence logs | `database/physical/06_permissions.sql`, `architecture/governance/security_and_privacy.md` | `validate_part3.py` scans 5 secret patterns; `test_analyst_cannot_read_ssn` passes | **Complete** |
| R1.5 | "safeguard... against potential bias... **limit the decision power** of such systems to ensure **fairness, accountability, and transparency**" | Named bias hazard (county health indicators proxy for race and income), six enforced controls, database-level human review gate, explicit decision-power limit | `architecture/governance/model_governance.md` § 4, 5, 11 | Test M7 confirms the database rejects an unattributed review | **Complete** |

## Deliverables

| ID | Requirement | File path | Status |
|----|-------------|-----------|--------|
| D1 | Physical model | `database/physical/*.sql`, `architecture/diagrams/part3_physical_model.svg` | **Complete** |
| D2 | Machine learning model(s) | `ml/models/*.joblib`, `ml/outputs/*` | **Complete** |
| D3 | Other relevant details | `docs/`, `workflows/`, `architecture/`, `database/evidence/` | **Complete** |
| D4 | Homework report (Word or text) | `report/Project_Part_III_Report.docx` and `.md` | **Complete** |
| D5 | Single zip archive named `lastname_p3_su26.zip` | `submission/Mo_p3_su26.zip` | **Complete** |

## Summary

| Status | Count |
|--------|-------|
| Complete | 29 |
| Partially complete | 0 |
| Not completed | 0 |
| Not applicable | 0 |

**All requirements are complete.** The cloud requirement (R3.5) was executed on 08/06/26 in
Google BigQuery: seven tables were loaded and four analytical queries were run, with every row
count verified against its local source.

One scope decision is recorded rather than hidden. Cloud Storage was not used, because it
requires an active billing account and both billing accounts on the student account were
closed. BigQuery Sandbox needs no billing account and is itself the public-cloud Big Data
analytics service the assignment names, so the extract, filter, store, analyze, and present
path was completed there. Cloud Storage remains in the future-state architecture.

Every cloud claim is backed by a file in `architecture/cloud_evidence/part3/`, and
`validate_part3.py` fails the build if the report claims execution while those files are
absent.
