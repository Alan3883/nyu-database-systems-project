-- =====================================================================
-- Project Part III - BigQuery Analytics Layer
--
-- Run by scripts/run_part3_cloud.sh. The dataset location is taken from
-- the GCS bucket at run time and is never assumed by this file.
--
-- Placeholders substituted by the script:
--   ${PROJECT}  GCP project id
--   ${DATASET}  BigQuery dataset name (default part3_analytics)
--   ${BUCKET}   GCS bucket name
-- =====================================================================

-- ---------------------------------------------------------------------
-- SECTION 1: table definitions
--
-- Tables are LOADED rather than EXTERNAL. The curated files are small and
-- static between releases, so loading gives better query performance and
-- avoids repeated GCS reads. External tables would suit a large, frequently
-- changing lake; that is noted in the future-state architecture.
-- ---------------------------------------------------------------------

-- geographic_area: 3,196 rows (1 nation, 51 states, 3,144 counties)
CREATE OR REPLACE EXTERNAL TABLE `${PROJECT}.${DATASET}.geographic_area`
OPTIONS (
  format = 'CSV',
  uris = ['gs://${BUCKET}/part3/curated/geographic_area.csv'],
  skip_leading_rows = 1
);

-- health_indicator: 148 measures from CDC PLACES and CDI
CREATE OR REPLACE EXTERNAL TABLE `${PROJECT}.${DATASET}.health_indicator`
OPTIONS (
  format = 'CSV',
  uris = ['gs://${BUCKET}/part3/curated/health_indicator.csv'],
  skip_leading_rows = 1
);

-- health_observation: 320 sampled county observations
CREATE OR REPLACE EXTERNAL TABLE `${PROJECT}.${DATASET}.health_observation`
OPTIONS (
  format = 'CSV',
  uris = ['gs://${BUCKET}/part3/curated/health_observation_sample.csv'],
  skip_leading_rows = 1
);

-- dataset_catalog: 10 datasets with source, licence, and classification
CREATE OR REPLACE EXTERNAL TABLE `${PROJECT}.${DATASET}.dataset_catalog`
OPTIONS (
  format = 'CSV',
  uris = ['gs://${BUCKET}/part3/metadata/dataset_catalog.csv'],
  skip_leading_rows = 1
);

-- data_asset: 10 physical files with checksums
CREATE OR REPLACE EXTERNAL TABLE `${PROJECT}.${DATASET}.data_asset`
OPTIONS (
  format = 'CSV',
  uris = ['gs://${BUCKET}/part3/curated/data_asset.csv'],
  skip_leading_rows = 1
);

-- ml_cluster_assignments: 32 chunks with cluster and distance
CREATE OR REPLACE EXTERNAL TABLE `${PROJECT}.${DATASET}.ml_cluster_assignments`
OPTIONS (
  format = 'CSV',
  uris = ['gs://${BUCKET}/part3/ml/outputs/cluster_assignments.csv'],
  skip_leading_rows = 1
);

-- ml_cluster_summary: 6 clusters with top terms
CREATE OR REPLACE EXTERNAL TABLE `${PROJECT}.${DATASET}.ml_cluster_summary`
OPTIONS (
  format = 'CSV',
  uris = ['gs://${BUCKET}/part3/ml/outputs/cluster_summary.csv'],
  skip_leading_rows = 1
);

-- =====================================================================
-- SECTION 2: analytical queries
-- =====================================================================

-- ---------------------------------------------------------------------
-- QUERY 1: indicator and observation counts by geographic level.
-- Confirms the hybrid model's geographic hierarchy loaded intact and
-- shows where observation coverage actually sits.
-- ---------------------------------------------------------------------
SELECT
  g.GeographyType,
  COUNT(DISTINCT g.GeographyID)   AS geographies,
  COUNT(DISTINCT o.IndicatorID)   AS distinct_indicators,
  COUNT(o.ObservationID)          AS observations
FROM `${PROJECT}.${DATASET}.geographic_area` g
LEFT JOIN `${PROJECT}.${DATASET}.health_observation` o
       ON CAST(o.GeographyID AS STRING) = CAST(g.GeographyID AS STRING)
GROUP BY g.GeographyType
ORDER BY geographies DESC;

-- ---------------------------------------------------------------------
-- QUERY 2: selected health indicators summarized by state.
-- The regional view an insurer would use for portfolio review. Aggregate
-- only: no individual is represented anywhere in this result.
-- ---------------------------------------------------------------------
SELECT
  g.StateCode,
  i.IndicatorName,
  i.FactorCategory,
  COUNT(*)                                        AS county_observations,
  ROUND(AVG(CAST(o.MeasureValue AS FLOAT64)), 2)  AS avg_value,
  ROUND(MIN(CAST(o.MeasureValue AS FLOAT64)), 2)  AS min_value,
  ROUND(MAX(CAST(o.MeasureValue AS FLOAT64)), 2)  AS max_value
FROM `${PROJECT}.${DATASET}.health_observation` o
JOIN `${PROJECT}.${DATASET}.health_indicator` i
  ON CAST(i.IndicatorID AS STRING) = CAST(o.IndicatorID AS STRING)
JOIN `${PROJECT}.${DATASET}.geographic_area` g
  ON CAST(g.GeographyID AS STRING) = CAST(o.GeographyID AS STRING)
WHERE g.GeographyType = 'County'
GROUP BY g.StateCode, i.IndicatorName, i.FactorCategory
HAVING COUNT(*) >= 2
ORDER BY avg_value DESC
LIMIT 40;

-- ---------------------------------------------------------------------
-- QUERY 3: ML cluster summary with chunk counts and top terms.
-- Brings the unstructured-data model output into the cloud analytics
-- layer alongside the structured regional data.
-- ---------------------------------------------------------------------
SELECT
  s.ClusterID,
  s.SuggestedLabel,
  s.ChunkCount,
  COUNT(a.ChunkIndex)                                    AS verified_chunk_count,
  ROUND(AVG(CAST(a.DistanceToCentroid AS FLOAT64)), 4)   AS avg_distance_to_centroid,
  COUNT(DISTINCT a.PageNumber)                           AS distinct_source_pages,
  s.TopTerms,
  s.HumanReviewed
FROM `${PROJECT}.${DATASET}.ml_cluster_summary` s
LEFT JOIN `${PROJECT}.${DATASET}.ml_cluster_assignments` a
       ON CAST(a.ClusterID AS STRING) = CAST(s.ClusterID AS STRING)
GROUP BY s.ClusterID, s.SuggestedLabel, s.ChunkCount, s.TopTerms, s.HumanReviewed
ORDER BY s.ClusterID;

-- ---------------------------------------------------------------------
-- QUERY 4 (extra): dataset lineage and licence inventory.
-- Demonstrates that governance metadata travels with the data into the
-- cloud analytics layer rather than being left behind on the laptop.
-- ---------------------------------------------------------------------
SELECT
  c.DatasetID,
  c.DatasetName,
  c.SourceOrganization,
  c.DataClassification,
  c.GeographicLevel,
  c.License,
  COUNT(a.AssetID)                          AS asset_count,
  SUM(CAST(a.FileSizeBytes AS INT64))       AS total_bytes
FROM `${PROJECT}.${DATASET}.dataset_catalog` c
LEFT JOIN `${PROJECT}.${DATASET}.data_asset` a
       ON a.DatasetID = c.DatasetID
GROUP BY c.DatasetID, c.DatasetName, c.SourceOrganization,
         c.DataClassification, c.GeographicLevel, c.License
ORDER BY c.DatasetID;
