-- =====================================================================
-- Project Part III - ML Result Constraint Tests
-- Target: PostgreSQL 16
--
-- Confirms the model governance rules are enforced by the database, not
-- only by convention in the pipeline code.
-- =====================================================================

\set ON_ERROR_STOP off
\echo '=== ML metadata and result constraint tests ==='

\echo ''
\echo '--- Loaded ML data ---'
SELECT 'ML_RUN' AS t, count(*) FROM ML_RUN
UNION ALL SELECT 'DOCUMENT_CHUNK', count(*) FROM DOCUMENT_CHUNK
UNION ALL SELECT 'ML_CLUSTER_RESULT', count(*) FROM ML_CLUSTER_RESULT
UNION ALL SELECT 'ML_CLUSTER_SUMMARY', count(*) FROM ML_CLUSTER_SUMMARY
ORDER BY 1;

\echo ''
\echo '--- Run metadata is complete and reproducible ---'
SELECT MLRunID, ModelName, ModelVersion, Algorithm, RandomSeed, TrainingDatasetID, Status,
       MetricsJSON ->> 'selected_k'           AS selected_k,
       MetricsJSON ->> 'silhouette_score'     AS silhouette,
       MetricsJSON ->> 'davies_bouldin_score' AS davies_bouldin,
       MetricsJSON ->> 'n_chunks'             AS n_chunks
FROM ML_RUN;

\echo ''
\echo 'TEST M1: chunk must reference a real DATA_ASSET'
INSERT INTO DOCUMENT_CHUNK (DataAssetID, PageNumber, ChunkText, WordCount, ChunkChecksum)
VALUES (999999, 1, 'test', 1, repeat('a', 64));
\echo '  ^ expected: violates foreign key on DataAssetID'

\echo ''
\echo 'TEST M2: page number must be positive'
INSERT INTO DOCUMENT_CHUNK (DataAssetID, PageNumber, ChunkText, WordCount, ChunkChecksum)
SELECT AssetID, 0, 'test', 1, repeat('b', 64) FROM DATA_ASSET
WHERE DatasetID='DS010' LIMIT 1;
\echo '  ^ expected: violates ck_chunk_page'

\echo ''
\echo 'TEST M3: duplicate chunk checksum for the same asset must be rejected'
INSERT INTO DOCUMENT_CHUNK (DataAssetID, PageNumber, ChunkText, WordCount, ChunkChecksum)
SELECT DataAssetID, PageNumber, ChunkText, WordCount, ChunkChecksum
FROM DOCUMENT_CHUNK LIMIT 1;
\echo '  ^ expected: violates uq_chunk_checksum'

\echo ''
\echo 'TEST M4: cluster result must reference a real run'
INSERT INTO ML_CLUSTER_RESULT (MLRunID, DocumentChunkID, ClusterID)
SELECT 999999, DocumentChunkID, 0 FROM DOCUMENT_CHUNK LIMIT 1;
\echo '  ^ expected: violates foreign key on MLRunID'

\echo ''
\echo 'TEST M5: a chunk cannot be assigned twice within one run'
INSERT INTO ML_CLUSTER_RESULT (MLRunID, DocumentChunkID, ClusterID)
SELECT MLRunID, DocumentChunkID, 99 FROM ML_CLUSTER_RESULT LIMIT 1;
\echo '  ^ expected: violates primary key (MLRunID, DocumentChunkID)'

\echo ''
\echo 'TEST M6: negative distance to centroid must be rejected'
-- Every existing chunk already has a result, so a throwaway chunk is created
-- first. Without it the INSERT would match no rows and the test would pass
-- vacuously without ever exercising the constraint.
INSERT INTO DOCUMENT_CHUNK (DataAssetID, PageNumber, ChunkText, WordCount, ChunkChecksum)
SELECT AssetID, 1, 'constraint test chunk', 3, repeat('c', 64)
FROM DATA_ASSET WHERE DatasetID='DS010' AND AssetType='unstructured document' LIMIT 1;

INSERT INTO ML_CLUSTER_RESULT (MLRunID, DocumentChunkID, ClusterID, DistanceToCentroid)
SELECT (SELECT MLRunID FROM ML_RUN ORDER BY MLRunID LIMIT 1),
       DocumentChunkID, 0, -1.0
FROM DOCUMENT_CHUNK WHERE ChunkChecksum = repeat('c', 64);
\echo '  ^ expected: violates ck_mlcr_distance'

-- Remove the throwaway chunk so it does not pollute the model results.
DELETE FROM DOCUMENT_CHUNK WHERE ChunkChecksum = repeat('c', 64);

\echo ''
\echo 'TEST M7 (GOVERNANCE): a cluster cannot be marked reviewed without a reviewer'
UPDATE ML_CLUSTER_SUMMARY SET HumanReviewed = TRUE WHERE ClusterID = 0;
\echo '  ^ expected: violates ck_mlcs_review - review requires ReviewedAt and ReviewedBy'

\echo ''
\echo 'TEST M8 (GOVERNANCE): a valid review is accepted'
UPDATE ML_CLUSTER_SUMMARY
SET HumanReviewed = TRUE, ReviewedAt = now(), ReviewedBy = 'analyst.demo',
    BusinessInterpretation = 'Reviewed: regional housing and income cost burden theme.'
WHERE ClusterID = 3;
SELECT ClusterID, ClusterLabel, HumanReviewed, ReviewedBy
FROM ML_CLUSTER_SUMMARY WHERE ClusterID = 3;

\echo ''
\echo '--- Referential integrity of ML results ---'
SELECT 'orphan ML_CLUSTER_RESULT.DocumentChunkID' AS check, count(*) AS violations
FROM ML_CLUSTER_RESULT r
LEFT JOIN DOCUMENT_CHUNK c ON c.DocumentChunkID = r.DocumentChunkID
WHERE c.DocumentChunkID IS NULL
UNION ALL
SELECT 'orphan ML_CLUSTER_SUMMARY.MLRunID', count(*)
FROM ML_CLUSTER_SUMMARY s LEFT JOIN ML_RUN r ON r.MLRunID = s.MLRunID
WHERE r.MLRunID IS NULL
UNION ALL
SELECT 'chunks assigned to a cluster not in the summary', count(*)
FROM ML_CLUSTER_RESULT r
LEFT JOIN ML_CLUSTER_SUMMARY s ON s.MLRunID=r.MLRunID AND s.ClusterID=r.ClusterID
WHERE s.ClusterID IS NULL
UNION ALL
SELECT 'chunks not traceable to DS010', count(*)
FROM DOCUMENT_CHUNK c
JOIN DATA_ASSET a ON a.AssetID = c.DataAssetID
WHERE a.DatasetID <> 'DS010';

\echo ''
\echo '--- Full lineage: cluster result back to the source dataset ---'
SELECT d.DatasetID, d.DatasetName, a.FileName, c.PageNumber,
       r.ClusterID, s.ClusterLabel, round(r.DistanceToCentroid, 4) AS distance
FROM ML_CLUSTER_RESULT r
JOIN DOCUMENT_CHUNK c ON c.DocumentChunkID = r.DocumentChunkID
JOIN DATA_ASSET a ON a.AssetID = c.DataAssetID
JOIN DATASET d ON d.DatasetID = a.DatasetID
JOIN ML_CLUSTER_SUMMARY s ON s.MLRunID = r.MLRunID AND s.ClusterID = r.ClusterID
ORDER BY r.ClusterID, r.DistanceToCentroid
LIMIT 8;

\echo ''
\echo '=== ML constraint tests complete ==='
