-- =====================================================================
-- Project Part III - Partitioning and Clustering Evaluation
-- Target: PostgreSQL 16
--
-- The assignment names partitioning and clustering as techniques to
-- consider "as applicable". This file records the evaluation and the
-- decision for each, and builds a clearly labelled synthetic table so the
-- growth-oriented design can be measured rather than asserted.
--
-- =====================================================================
-- DECISION 1: PARTITIONING - EVALUATED, NOT APPLIED TO PRODUCTION TABLES
-- =====================================================================
-- HEALTH_OBSERVATION currently holds 320 curated sample rows in a single
-- heap of well under one page. Partitioning it would:
--   - add planning overhead on every query,
--   - create empty partitions,
--   - and produce no measurable read benefit.
-- Partitioning is therefore NOT applied to the live table.
--
-- The growth design is real, though, and is demonstrated below on a
-- synthetic table. Candidates identified for production scale:
--   HEALTH_OBSERVATION    RANGE BY ObservationYear
--   QUOTE_STATUS_HISTORY  RANGE BY ChangedAt (monthly)
--   ML_CLUSTER_RESULT     RANGE BY model run date
--
-- The trigger to adopt partitioning is a table exceeding roughly 50-100
-- million rows, or a retention policy requiring whole-period drops.
-- Partitioning's strongest benefit here is not read speed but
-- maintenance: DROP PARTITION removes a year instantly, where DELETE
-- would rewrite the table and bloat it.
-- =====================================================================

\echo 'Building synthetic performance dataset (clearly labelled, outside the data lake)...'

-- ---------------------------------------------------------------------
-- Synthetic scale table.
--
-- NAMING: the perf_ prefix and the _synthetic suffix mark this as
-- generated test data. It is never written to the data lake, never
-- exported to the curated zone, and never uploaded to cloud storage.
-- It exists only to measure index behaviour at production scale.
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS perf_health_observation_synthetic CASCADE;

CREATE TABLE perf_health_observation_synthetic (
    ObservationID   BIGINT PRIMARY KEY,
    DatasetID       VARCHAR(10)  NOT NULL,
    GeographyID     INTEGER      NOT NULL,
    IndicatorID     INTEGER      NOT NULL,
    ObservationYear INTEGER      NOT NULL,
    MeasureValue    NUMERIC(12,4),
    IsSynthetic     BOOLEAN      NOT NULL DEFAULT TRUE
);

COMMENT ON TABLE perf_health_observation_synthetic IS
    'SYNTHETIC performance-test data. Generated, not observed. Never part of the data lake or any analytical result.';

-- 500,000 rows spanning the real key ranges: 3,144 counties, 148
-- indicators, 10 years. Deterministic, so the test is repeatable.
INSERT INTO perf_health_observation_synthetic
    (ObservationID, DatasetID, GeographyID, IndicatorID, ObservationYear, MeasureValue)
SELECT gs,
       'DS001',
       1000 + (gs % 3144),
       1 + (gs % 148),
       2015 + (gs % 10),
       round((10 + (gs % 400) / 10.0)::numeric, 4)
FROM generate_series(1, 500000) gs;

ANALYZE perf_health_observation_synthetic;

-- The same composite index shape applied to the live table, so the two
-- can be compared directly.
CREATE INDEX ix_perf_obs_geo_ind_year
    ON perf_health_observation_synthetic (GeographyID, IndicatorID, ObservationYear);

ANALYZE perf_health_observation_synthetic;

-- ---------------------------------------------------------------------
-- Partitioned variant, to show the growth design is workable.
-- RANGE partitioning by ObservationYear with one partition per year.
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS perf_health_observation_partitioned CASCADE;

CREATE TABLE perf_health_observation_partitioned (
    ObservationID   BIGINT       NOT NULL,
    DatasetID       VARCHAR(10)  NOT NULL,
    GeographyID     INTEGER      NOT NULL,
    IndicatorID     INTEGER      NOT NULL,
    ObservationYear INTEGER      NOT NULL,
    MeasureValue    NUMERIC(12,4),
    -- The partition key must be part of the primary key in a partitioned
    -- table. This is a real design consequence of choosing partitioning.
    PRIMARY KEY (ObservationID, ObservationYear)
) PARTITION BY RANGE (ObservationYear);

COMMENT ON TABLE perf_health_observation_partitioned IS
    'SYNTHETIC. Demonstrates the growth-oriented RANGE partitioning design for HEALTH_OBSERVATION.';

-- One partition per year, 2015-2024.
DO $$
DECLARE y INT;
BEGIN
    FOR y IN 2015..2024 LOOP
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS perf_obs_y%s PARTITION OF perf_health_observation_partitioned '
            'FOR VALUES FROM (%s) TO (%s)', y, y, y + 1);
    END LOOP;
END
$$;

INSERT INTO perf_health_observation_partitioned
    (ObservationID, DatasetID, GeographyID, IndicatorID, ObservationYear, MeasureValue)
SELECT ObservationID, DatasetID, GeographyID, IndicatorID, ObservationYear, MeasureValue
FROM perf_health_observation_synthetic;

CREATE INDEX ix_perf_part_geo_ind
    ON perf_health_observation_partitioned (GeographyID, IndicatorID);

ANALYZE perf_health_observation_partitioned;

-- =====================================================================
-- DECISION 2: CLUSTERING - EVALUATED, APPLIED ONCE TO ONE TABLE
-- =====================================================================
-- PostgreSQL CLUSTER physically reorders a table to match an index.
--
-- Two properties drive the decision:
--   1. It is a ONE-TIME reorganisation. PostgreSQL does NOT maintain the
--      order afterwards. New and updated rows go wherever there is free
--      space, so the ordering decays with every write.
--   2. It takes an ACCESS EXCLUSIVE lock, blocking all reads and writes
--      for the duration.
--
-- CLUSTER is therefore only justified where:
--   - reads are dominated by range access on one index, and
--   - the table is rarely updated, so the ordering does not decay, and
--   - a maintenance window exists.
--
-- HEALTH_OBSERVATION fits: it is bulk-loaded once per release, never
-- updated in place, and is read by geography ranges. Clustering it on
-- ix_obs_geo_ind_year puts all observations for a county on the same few
-- pages, which cuts random I/O for the hybrid join.
--
-- NOT clustered: ACCOUNT, CUSTOMER, CONTRACT, QUOTE. All are
-- update-heavy, so ordering would decay immediately and the exclusive
-- lock cost would buy nothing.
-- =====================================================================

\echo 'Applying CLUSTER to the synthetic table to measure the effect...'

CLUSTER perf_health_observation_synthetic USING ix_perf_obs_geo_ind_year;
ANALYZE perf_health_observation_synthetic;

-- Re-clustering after a future bulk load is a single command:
--   CLUSTER perf_health_observation_synthetic;
-- which reuses the index recorded by the first CLUSTER.

\echo 'Partitioning and clustering evaluation complete.'
