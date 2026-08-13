# Query Plan Summary

Measured on PostgreSQL 16.14 in Docker container `part2-postgres`, database `part3`.
Every number below comes from `EXPLAIN (ANALYZE, BUFFERS)` and is reproducible with
`python3 scripts/run_performance_tests.py --phase after`.

Raw plans: `explain_before_output.txt`, `explain_after_output.txt`.
Tabulated results: `performance_results.csv`.

---

## 1. The honest headline

At curated-sample scale most Part III indexes are **not used**, and that is the correct
planner behaviour rather than a defect. `ACCOUNT` holds 50 rows, `DATA_ASSET` holds 10, and
`ACCOUNT_GEOGRAPHY` holds 50. A table that fits in one or two 8 KB pages is cheaper to scan
sequentially than to read through an index, because the index adds a second structure to
traverse for no I/O saving.

Reporting these as improvements would be false. They are reported as sequential scans with
the reason recorded in the `Notes` column of `performance_results.csv`.

The index design is still correct, and that claim is tested rather than asserted: a
clearly labelled synthetic table of 500,000 rows demonstrates the behaviour the indexes
exist for.

## 2. Where optimization measurably changed the plan

| Query | Before | After | Change |
|-------|--------|-------|--------|
| Q04 account-to-active-contract | `ix_contract_account` (Part II, full index) | `ix_contract_account_active` (Part III, partial) | Planner switched to the partial index, which contains only active contracts |
| Q07 county FIPS lookup | `ix_geography_countyfips` (Part II) | `ix_geo_countyfips_partial` (Part III) | Planner switched to the partial index that excludes NULL FIPS rows |
| Q08 five-table hybrid join | 0.081 ms | 0.072 ms | Modest gain from `ix_obs_geo_ind_year` |
| Q13 regional aggregation | 0.284 ms | 0.246 ms | Modest gain from the covering index |

## 3. Materialized view result

The signature hybrid query joins five tables. `MV_ACCOUNT_REGIONAL_HEALTH_PROFILE`
pre-computes it.

| Query | Path | Execution time |
|-------|------|----------------|
| Q08 | Live five-table join | 0.072 ms |
| Q16 | Materialized view read | 0.027 ms |

**2.7x faster** at sample scale, with no join work performed at read time. The gap widens
with data volume because the join cost grows with the number of observations while the
view read grows only with the number of result rows.

Refresh cost is paid once per curated load, not once per reader.

## 4. Index benefit at production scale

Table: `perf_health_observation_synthetic`, 500,000 generated rows, clearly labelled as
synthetic and never written to the data lake.

Query: `SELECT * FROM perf_health_observation_synthetic WHERE GeographyID=1500 AND IndicatorID=20`

| Configuration | Plan | Execution time |
|---------------|------|----------------|
| With `ix_perf_obs_geo_ind_year` | Index Scan | **0.032 ms** |
| Index dropped | Parallel Seq Scan | **7.121 ms** |

**222x reduction.** This is the measured justification for the composite index shape
`(GeographyID, IndicatorID, ObservationYear)` applied to the live `HEALTH_OBSERVATION`
table, which today is too small to show the effect itself.

## 5. Partitioning evaluation, measured

Two synthetic tables hold identical data: one plain, one RANGE-partitioned by
`ObservationYear` into ten yearly partitions.

**Case A: point lookup with a year predicate**

| Table | Plan | Time | Buffers |
|-------|------|------|---------|
| Partitioned | Bitmap scan on `perf_obs_y2019` only (pruning worked) | 0.158 ms | 34 |
| Non-partitioned | Index Only Scan on the composite index | **0.070 ms** | **6** |

Partition pruning worked correctly, but the non-partitioned table with a good composite
index was still **2.3x faster** and touched **5.7x fewer buffers**. For point lookups, a
well-chosen index beats partitioning.

**Case B: full-period scan**

`SELECT avg(MeasureValue) ... WHERE ObservationYear=2019`

| Table | Plan | Buffers |
|-------|------|---------|
| Partitioned | Seq Scan on one partition | **417** |
| Non-partitioned | Parallel Seq Scan over the whole table | 4,167 |

Here partitioning wins: pruning removed 90% of the I/O because only one tenth of the data
had to be read.

**Conclusion.** Partitioning helps period-scoped scans and whole-period maintenance; it does
not help point lookups. `HEALTH_OBSERVATION` currently holds 320 rows, so partitioning is
**evaluated and documented but not applied** to the live table. The growth design is proven
to work and is ready to adopt when volume justifies it.

## 6. Clustering evaluation

`CLUSTER perf_health_observation_synthetic USING ix_perf_obs_geo_ind_year` was executed
successfully.

Two properties decide where it is appropriate:

1. It is a **one-time** physical reorganisation. PostgreSQL does not maintain the ordering,
   so it decays as rows are inserted and updated.
2. It takes an **ACCESS EXCLUSIVE** lock for the duration, blocking all readers and writers.

Applied to `HEALTH_OBSERVATION`-shaped data, which is bulk-loaded once per release, never
updated in place, and read by geographic range: the ordering does not decay between loads,
so the one-time cost is recovered.

Not applied to `ACCOUNT`, `CUSTOMER`, `CONTRACT`, or `QUOTE`. All are update-heavy, so the
ordering would decay immediately and the exclusive lock would buy nothing.

## 7. What this means for the design

| Technique | Verdict | Evidence |
|-----------|---------|----------|
| Indexing | **Applied.** 16 new indexes, all workload-driven (87 total on the database; see the note below) | 222x gain measured at 500k rows; two plan switches at sample scale |
| Partitioning | **Evaluated, not applied** to live tables | Measured: helps scans 10x, hurts point lookups 2.3x; live table has 320 rows |
| Clustering | **Evaluated, applied to one insert-only table shape** | Executed successfully; rejected for all update-heavy tables with stated reasons |
| Selective materialization | **Applied.** One view on the signature hybrid path | 2.7x faster than the equivalent live join |

The general principle the measurements support: physical design decisions must be tied to a
measured workload and a real data volume. The same index that gives a 222x gain on 500,000
rows is correctly ignored by the planner on 50 rows.

## 8. Index count note

Three counts appear in this project and measure different things:

| Figure | Count | Meaning |
|--------|-------|---------|
| Part II baseline | 52 | 23 named `ix_` indexes + 29 PK/UNIQUE backing indexes |
| Part III new explicit indexes | 16 | Added by `02_indexes.sql`, each tied to a workload query |
| All `ix_` prefixed | 42 | 23 Part II + 16 Part III + 3 on the materialized view |
| Part III total | 87 | 52 + 16 + 15 PK/UNIQUE on the 10 new tables + 4 materialized view |

A further 24 indexes exist on the two synthetic performance tables and are excluded from every
figure above.
