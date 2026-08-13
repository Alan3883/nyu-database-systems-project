# Data Lineage

Every derived artefact can be traced back to an official source file.

## 1. Structured path

```
Official source URL
  -> raw/<folder>/<file>            SHA-256 recorded in download_manifest.json
  -> processed/cdc_places_county_clean.csv     03_build_curated_data.py
  -> curated/{geographic_area, health_indicator, health_observation_sample,
              dataset, data_asset}.csv        03_build_curated_data.py, seed 42
  -> PostgreSQL GEOGRAPHIC_AREA / HEALTH_INDICATOR / HEALTH_OBSERVATION
                                              load_curated_to_postgres.py
  -> MV_ACCOUNT_REGIONAL_HEALTH_PROFILE       05_materialized_views.sql
  -> Regional portfolio review
```

## 2. Unstructured path (DS010)

```
https://www.countyhealthrankings.org/.../2025 CHRR Report_0.pdf
  -> raw/unstructured_documents/chr_2025_national_report.pdf   14,580,902 bytes
  -> checksum verified against download_manifest.json          discover_ds010.py
  -> 18 pages of text, running headers stripped                extract_pdf.py
  -> 32 paragraph chunks, page numbers preserved               build_chunks.py
  -> TF-IDF matrix, 520 terms                                  train_cluster_model.py
  -> K-means K=6, seed 42
  -> ml/outputs/*.csv, *.json, *.png                           export_results.py
  -> PostgreSQL DOCUMENT_CHUNK / ML_RUN /
     ML_CLUSTER_RESULT / ML_CLUSTER_SUMMARY                    load_ml_results_to_postgres.py
  -> business_insights.md  (unreviewed)
  -> human review gate  ->  approved business use
```

## 3. In-database lineage chain

```
DATASET (DS010)
  -> DATA_ASSET (AssetID 10, chr_2025_national_report.pdf, SHA-256)
     -> DOCUMENT_CHUNK (32 rows, PageNumber preserved)
        -> ML_CLUSTER_RESULT (32 rows, MLRunID + ClusterID + distance)
           -> ML_CLUSTER_SUMMARY (6 clusters, top terms, review state)
ML_RUN (config, seed, metrics) ties the run to DATASET via TrainingDatasetID
```

This chain is exercised by a live query in
`database/tests/ml_result_constraint_tests.sql`, which joins a cluster result back to its
source dataset and file name. The test `document_chunk -> ds010` confirms no chunk originates
from any other dataset.

## 4. Recorded lineage files

| File | Grain |
|------|-------|
| `metadata/lineage.csv` | Source file → transformation → output file → script |
| `metadata/file_inventory.csv` | Every file with SHA-256 |
| `metadata/download_manifest.json` | Source URL, size, checksum, status per dataset |
| `ml/outputs/ds010_chunks.csv` | Chunk → page number → checksum |
| `ml/outputs/cluster_assignments.csv` | Chunk → cluster → distance |
| `database/evidence/performance_results.csv` | Query → plan → measurement |

## 5. Reproducibility guarantee

Any consumer can reconstruct every derived artefact:

1. `python3 scripts/download_part2_data.py` — fetch sources (checksums must match)
2. `python3 scripts/03_build_curated_data.py` — rebuild curated tables (seed 42)
3. `python3 -m ml.src.run_pipeline` — retrain the model (seed 42, byte-identical output)
4. `bash scripts/run_part3_database.sh` — rebuild the database

Reproducibility is asserted by `ml/tests/test_reproducibility.py` and by re-running the
pipeline and comparing checksums.

## 6. Change detection

| Artefact | Detector |
|----------|----------|
| Raw file altered | SHA-256 against `download_manifest.json` |
| Extracted text drifted | `DOCUMENT_CHUNK.ChunkChecksum` |
| Model changed | `ML_RUN.MetricsJSON` compared across runs |
| Materialized view stale | `V_MV_ARHP_VALIDATION` compares against the live join |
