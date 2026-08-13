-- =====================================================================
-- Part III - Query plans AFTER physical optimization
--
-- Same queries as explain_before.sql, plus queries on the Part III
-- workflow, ML, materialized view, and synthetic scale tables.
--
-- Reproduce with:
--   python3 scripts/run_performance_tests.py --phase after
-- Captured output: database/evidence/explain_after_output.txt
-- Analysis:        database/evidence/query_plan_summary.md
-- =====================================================================

-- Expect: ix_contract_account_active (partial index) replaces the Part II index.
EXPLAIN (ANALYZE, BUFFERS)
SELECT ContractID, ContractNumber, PlanName, EffectiveDate FROM CONTRACT
WHERE AccountID=12 AND Status='Active' ORDER BY EffectiveDate DESC;

-- Expect: ix_geo_countyfips_partial.
EXPLAIN (ANALYZE, BUFFERS)
SELECT g.CountyFIPS, g.GeographyName, hi.IndicatorName, ho.MeasureValue
FROM GEOGRAPHIC_AREA g
JOIN HEALTH_OBSERVATION ho ON ho.GeographyID=g.GeographyID
JOIN HEALTH_INDICATOR hi ON hi.IndicatorID=ho.IndicatorID
WHERE g.CountyFIPS='05119';

-- The live five-table join, for comparison against the materialized view below.
EXPLAIN (ANALYZE, BUFFERS)
SELECT a.AccountID, a.AccountName, g.CountyFIPS, hi.IndicatorName, ho.MeasureValue
FROM ACCOUNT a
JOIN ACCOUNT_GEOGRAPHY ag ON ag.AccountID=a.AccountID
JOIN GEOGRAPHIC_AREA g ON g.GeographyID=ag.GeographyID
JOIN HEALTH_OBSERVATION ho ON ho.GeographyID=g.GeographyID
JOIN HEALTH_INDICATOR hi ON hi.IndicatorID=ho.IndicatorID
WHERE a.AccountID=12;

-- MATERIALIZED VIEW: same result, no join work at read time.
EXPLAIN (ANALYZE, BUFFERS)
SELECT AccountID, AccountName, CountyFIPS, IndicatorName, MeasureValue
FROM MV_ACCOUNT_REGIONAL_HEALTH_PROFILE WHERE AccountID=12;

-- Partial index on the open-quote work queue.
EXPLAIN (ANALYZE, BUFFERS)
SELECT QuoteID, QuoteNumber, QuoteStatus, RequestedDate FROM QUOTE
WHERE QuoteStatus IN ('Draft','Submitted','Rated','Presented')
ORDER BY RequestedDate DESC LIMIT 50;

-- ML result lookup by run and cluster.
EXPLAIN (ANALYZE, BUFFERS)
SELECT mcr.ClusterID, mcr.DistanceToCentroid, dc.PageNumber
FROM ML_CLUSTER_RESULT mcr
JOIN DOCUMENT_CHUNK dc ON dc.DocumentChunkID=mcr.DocumentChunkID
WHERE mcr.MLRunID=1 AND mcr.ClusterID=0 ORDER BY mcr.DistanceToCentroid;

-- =====================================================================
-- SCALE EVIDENCE: 500,000 synthetic rows.
-- This is where the composite index earns its place. With the index the
-- query runs in 0.032 ms; without it, 7.121 ms (Parallel Seq Scan).
-- =====================================================================
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM perf_health_observation_synthetic
WHERE GeographyID=1500 AND IndicatorID=20;

-- Partition pruning: only perf_obs_y2019 is scanned.
EXPLAIN (ANALYZE, BUFFERS)
SELECT avg(MeasureValue) FROM perf_health_observation_partitioned
WHERE ObservationYear=2019;
