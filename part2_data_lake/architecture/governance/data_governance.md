# Data Governance

Covers ownership, authority, metadata, versioning, retention, and approval for every dataset
in the project.

## 1. Dataset ownership and source authority

| Dataset | Source organization | Authority | Owner role |
|---------|--------------------|-----------|------------|
| DS001 CDC PLACES County | CDC | U.S. federal public health agency | Data engineering |
| DS002 Chronic Disease Indicators | CDC | U.S. federal public health agency | Data engineering |
| DS003-DS005 County Health Rankings | University of Wisconsin Population Health Institute | Academic public health program | Data engineering |
| DS006-DS009 ACS 5-Year | U.S. Census Bureau | U.S. federal statistical agency | Data engineering |
| DS010 CHR&R 2025 Report | University of Wisconsin Population Health Institute | Academic public health program | Data engineering |
| Internal insurance data | The insurer | Business system of record | Business data owner |

All ten public datasets are published for public use. Licence text is recorded per dataset in
`metadata/dataset_catalog.csv` (`License` column).

## 2. Metadata management

Four metadata artefacts, all machine-readable:

| Artefact | Content |
|----------|---------|
| `metadata/dataset_catalog.csv` | 15 fields per dataset: source, URL, classification, geography, period, subject, key fields, zone, related EDA entity, update frequency, licence |
| `metadata/data_dictionary.csv` | Actual source columns with null counts and sample values |
| `metadata/file_inventory.csv` | Every file with size, row/column counts, SHA-256 |
| `metadata/lineage.csv` | Source file to output file with the transformation and the script |

Inside the database the same information is queryable through `DATASET` and `DATA_ASSET`,
which is how the ML pipeline locates DS010 rather than hard-coding a path.

## 3. Schema versioning

| Layer | Version control |
|-------|-----------------|
| Logical schema | `logical_model/logical_schema.sql`, unchanged since Part II |
| Physical layer | `database/physical/01`-`07`, additive only |
| Rollback | `database/physical/rollback.sql` returns the database to its Part II state |
| Model schema version | `DATA_ASSET.SchemaVersion`; `ML_RUN.ModelVersion` |

The Part II logical schema is treated as an immutable input. Part III adds files rather than
editing it, so the Part II deliverable remains exactly as submitted.

## 4. Retention

| Data class | Retention | Rationale |
|------------|-----------|-----------|
| Raw public files | Indefinite, immutable | Reproducibility; checksums must keep matching |
| Processed and curated | Regenerated per release | Derived; rebuildable from raw |
| Metadata and lineage | Indefinite | Audit trail |
| Quote records | 7 years after closure | Typical insurance record retention |
| `QUOTE_STATUS_HISTORY` | Same as the quote, append-only | Audit integrity |
| Contract, benefit, premium | Policy life + statutory period | Regulatory |
| ML runs and results | Indefinite while the model is in use | Model audit |
| Synthetic performance data | Discard freely | Generated, never a business record |

Part I recorded a 13-month history requirement, honoured through StartDate/EndDate rather
than physical deletion.

## 5. Data lineage

Full path from source to business use is documented in `data_lineage.md` and recorded in
`metadata/lineage.csv`. In the database the chain is:

`DATASET` → `DATA_ASSET` → `DOCUMENT_CHUNK` → `ML_CLUSTER_RESULT` → `ML_CLUSTER_SUMMARY`

Verified by a live query in `database/tests/ml_result_constraint_tests.sql`, which joins a
cluster result back to its source dataset.

## 6. Approval responsibility

| Decision | Approver |
|----------|----------|
| Adding a dataset to the lake | Data engineering |
| Promoting curated data to the ODS | Data engineering + business data owner |
| Approving a cluster interpretation | Reviewing analyst, recorded in `ML_CLUSTER_SUMMARY.ReviewedBy` |
| Using regional data in any customer-facing process | Underwriting leadership + compliance |
| Deploying to cloud | Project owner holding the credentials |

## 7. Preventing a data swamp

The assignment warns about lakes becoming unusable "data swamps". Four controls:

1. **Nothing enters raw without a catalogue entry.** Every file has a DS ID, source URL, and licence.
2. **Every file carries a checksum.** All 10 raw files verified unchanged at packaging time.
3. **Every derived file records its lineage.** `metadata/lineage.csv` names the script.
4. **Zones have defined meanings.** Raw is immutable, processed is standardized, curated matches
   the hybrid schema, metadata describes the rest.

## 8. Growth design

| Dimension | Current | Growth path |
|-----------|---------|-------------|
| Datasets | 10 | Catalogue-driven; adding a dataset requires no schema change |
| Unstructured docs | 1 | `DOCUMENT_CHUNK.DataAssetID` already supports many assets |
| Observations | 320 sample | Partitioning design proven on 500k synthetic rows |
| Model runs | 1 | `ML_RUN` versioned; multiple runs comparable via `ix_mlcr_chunk` |
| Cloud | GCS + BigQuery | Future-state services labelled planned, not deployed |
