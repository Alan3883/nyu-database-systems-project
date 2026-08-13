# Data Quality

Defines the quality checks applied across the lake and the database, and records the measured
results.

## 1. Check inventory

| # | Check | Where enforced | Result |
|---|-------|----------------|--------|
| 1 | Missing keys | `04_validate_outputs.py`; NOT NULL constraints | Pass |
| 2 | Duplicate keys | Primary keys; `pk_unique` checks | Pass, 0 duplicates |
| 3 | Invalid FIPS codes | 5-digit regex check | Pass, 0 invalid of 3,144 counties |
| 4 | Invalid date ranges | `ck_*_dates` constraints | Pass, 3 negative tests fired |
| 5 | Broken foreign keys | 33 FK constraints + orphan queries | Pass, 0 orphans across 9 checks |
| 6 | Missing asset paths | `DATA_ASSET.RelativePath` populated | Pass, 10 of 10 |
| 7 | Checksum mismatch | SHA-256 verified against manifest | Pass, 10 of 10 match |
| 8 | Empty PDF pages | Counted, not hidden | 0 of 18 pages failed |
| 9 | Empty chunks | `drop_empty_chunks`; `ck_chunk_words` | Pass, 0 empty |
| 10 | Duplicate chunks | Checksum dedup; `uq_chunk_checksum` | Pass, 0 duplicates |
| 11 | Invalid cluster references | FK + `ck_mlcr_cluster` | Pass, 0 invalid |
| 12 | Invalid observation years | `ck_observation_year` (1990-2026) | Pass, negative test fired |
| 13 | Numeric conversion failures | Recorded in `data_quality_report.csv` | Recorded |
| 14 | Inconsistent column names | Standardized in the processed zone | Applied |

## 2. Measured source quality

From `metadata/data_quality_report.csv`:

| Dataset | Rows | Cols | Duplicate rows | Missing cells | Missing % |
|---------|------|------|----------------|---------------|-----------|
| DS001 CDC PLACES | 229,298 | 22 | 0 | 458,794 | 9.09% |
| DS002 Chronic Disease Indicators | 398,793 | 34 | 0 | 5,098,425 | 37.60% |
| DS004 CHR analytic | 3,204 | 796 | 0 | 1,287,460 | 50.48% |
| DS009 ACS S2701 | 3,222 | 1,225 | 0 | 1,955,256 | 49.54% |

High missing rates in the wide files are expected: most columns hold race or age breakdowns
that are suppressed for small counties, plus confidence-limit and footnote columns. This is a
property of the sources, not a processing defect.

## 3. Known data quality issues found and handled

| Issue | Detection | Resolution |
|-------|-----------|------------|
| National aggregate rows with blank county names in PLACES | NOT NULL violation during the database load | Curated builder excludes `StateAbbr='US'` |
| Second header row in the CHR analytic CSV | Manual inspection | Header handling in the profiling script |
| Census API key embedded in the download manifest | Credential scan | Redacted to `<CENSUS_API_KEY>` |
| Folder-level dataset mapping mislabelled 7 files | Review of `data_asset.csv` | Exact path mapping from the download manifest |
| Citation boilerplate forming its own ML cluster | Cluster inspection | Documented as an artefact in `business_insights.md` |

## 4. ML corpus quality

| Metric | Value |
|--------|-------|
| PDF pages | 18 |
| Pages yielding usable text | 18 |
| Pages failing extraction | 0 |
| Total extractable words | 4,224 |
| Chunks built | 32 |
| Chunks below the word floor | 0 |
| Duplicate chunks removed | 0 |
| Running headers stripped | Yes, verified by test |

## 5. Continuous checks

| Suite | Count | Command |
|-------|-------|---------|
| Data lake validation | 14 checks | `python3 scripts/04_validate_outputs.py` |
| Database tests | 78 tests | `python3 -m pytest database/tests/test_database.py` |
| ML tests | 44 tests | `python3 -m pytest ml/tests` |
| SQL constraint tests | 23 negative tests | `psql -f database/tests/*.sql` |

All suites exit nonzero on failure so they can gate a pipeline.
