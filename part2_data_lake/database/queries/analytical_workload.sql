-- =====================================================================
-- Project Part III - Analytical Workload
-- Target: PostgreSQL 16
--
-- Longer aggregate queries used for regional review and model audit.
-- Query IDs Q13-Q14 continue the numbering from operational_workload.sql.
-- =====================================================================

-- Q13 Regional indicator aggregation.
-- Served by the covering index ix_obs_ind_geo_covering, which carries
-- MeasureValue in its INCLUDE payload so the aggregate can be satisfied
-- without heap access.
SELECT hi.IndicatorName,
       hi.FactorCategory,
       g.StateCode,
       count(*)                        AS observation_count,
       round(avg(ho.MeasureValue), 2)  AS avg_value,
       round(min(ho.MeasureValue), 2)  AS min_value,
       round(max(ho.MeasureValue), 2)  AS max_value
FROM HEALTH_OBSERVATION ho
JOIN HEALTH_INDICATOR hi ON hi.IndicatorID = ho.IndicatorID
JOIN GEOGRAPHIC_AREA   g ON g.GeographyID  = ho.GeographyID
WHERE hi.FactorCategory = 'Disease outcome'
GROUP BY hi.IndicatorName, hi.FactorCategory, g.StateCode
ORDER BY avg_value DESC
LIMIT 25;

-- Q14 Dataset and model-run audit lookup.
-- Served by ix_mlrun_dataset_started. Answers "what has been trained on
-- this dataset, when, with what seed, and what did it score".
SELECT d.DatasetID,
       d.DatasetName,
       r.MLRunID,
       r.ModelName,
       r.ModelVersion,
       r.Algorithm,
       r.RandomSeed,
       r.Status,
       r.StartedAt,
       r.CompletedAt,
       r.MetricsJSON ->> 'silhouette_score'     AS silhouette,
       r.MetricsJSON ->> 'davies_bouldin_score' AS davies_bouldin,
       r.MetricsJSON ->> 'n_chunks'             AS n_chunks
FROM ML_RUN r
JOIN DATASET d ON d.DatasetID = r.TrainingDatasetID
WHERE r.TrainingDatasetID = 'DS010'
ORDER BY r.StartedAt DESC;

-- Q15 Cluster summary with chunk counts. Used for the report table and
-- mirrored by the BigQuery analytics layer.
SELECT s.ClusterID,
       s.ClusterLabel,
       count(r.DocumentChunkID)                    AS chunk_count,
       round(avg(r.DistanceToCentroid)::numeric, 4) AS avg_distance,
       s.HumanReviewed,
       s.TopTermsJSON
FROM ML_CLUSTER_SUMMARY s
LEFT JOIN ML_CLUSTER_RESULT r
       ON r.MLRunID = s.MLRunID AND r.ClusterID = s.ClusterID
WHERE s.MLRunID = 1
GROUP BY s.ClusterID, s.ClusterLabel, s.HumanReviewed, s.TopTermsJSON
ORDER BY s.ClusterID;

-- Q16 Materialized view read: the same result as Q08 but pre-joined.
-- Compare this plan against Q08 to see the materialization benefit.
SELECT AccountID, AccountName, CountyFIPS, GeographyName,
       IndicatorName, FactorCategory, MeasureValue, ObservationYear
FROM MV_ACCOUNT_REGIONAL_HEALTH_PROFILE
WHERE AccountID = 12;

-- Q17 Portfolio review: accounts ranked by a regional indicator.
-- Reads only the materialized view.
SELECT FactorCategory,
       count(DISTINCT AccountID)          AS accounts,
       count(*)                           AS observations,
       round(avg(MeasureValue), 2)        AS avg_measure
FROM MV_ACCOUNT_REGIONAL_HEALTH_PROFILE
GROUP BY FactorCategory
ORDER BY accounts DESC;
