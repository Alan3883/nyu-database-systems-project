-- =====================================================================
-- Project Part III - Operational Workload
-- Target: PostgreSQL 16
--
-- Short, high-frequency queries that an application issues while serving
-- users. These drive the index decisions in 02_indexes.sql.
-- Query IDs Q01-Q12 are referenced by the index comments and by
-- database/evidence/performance_results.csv.
-- =====================================================================

-- Q01 Account lookup by business key.
-- Uses the Part II unique constraint uq_account_business.
SELECT AccountID, AccountName, AccountType, Status
FROM ACCOUNT
WHERE AccountName = 'Demo Account 7'
  AND Address1    = '7 Main St'
  AND City        = 'City7'
  AND State       = 'AR'
  AND Zip         = '70007'
  AND CompanyCode = 'DEMO7';

-- Q02 Customer lookup by name.
-- Served by ix_customer_name (CustLastName, CustFirstName).
SELECT CustomerID, CustLastName, CustFirstName, CustomerType, Status
FROM CUSTOMER
WHERE CustLastName = 'Last42';

-- Q03 Contract lookup by contract number.
-- Served by the Part II unique constraint uq_contract_number.
SELECT ContractID, ContractNumber, AccountID, LineOfBusiness, PlanName, Status
FROM CONTRACT
WHERE ContractNumber = 'C-000123';

-- Q04 Account-to-contract retrieval, active contracts only.
-- Served by the partial index ix_contract_account_active. The predicate
-- Status = 'Active' must be present for the planner to use it.
SELECT c.ContractID, c.ContractNumber, c.PlanName, c.EffectiveDate
FROM CONTRACT c
WHERE c.AccountID = 12
  AND c.Status = 'Active'
ORDER BY c.EffectiveDate DESC;

-- Q05 Associate-to-contract retrieval through the manager contract and
-- premium credit path.
-- Served by ix_premium_mgr_year.
SELECT a.AssociateID, a.AssocLastName, mc.WritingNumber, mc.SitCode,
       cp.YearNumber, SUM(cp.AnnualizedPremium) AS total_premium
FROM ASSOCIATE a
JOIN MANAGER_CONTRACT mc ON mc.AssociateID = a.AssociateID
JOIN CONTRACT_PREMIUM cp ON cp.ManagerContractID = mc.ManagerContractID
WHERE cp.YearNumber = 2021
GROUP BY a.AssociateID, a.AssocLastName, mc.WritingNumber, mc.SitCode, cp.YearNumber;

-- Q06 Account-to-geographic-area retrieval (reverse direction: which
-- accounts sit in a given area).
-- Served by ix_acctgeo_geo_type.
SELECT ag.AccountID, a.AccountName, ag.RelationshipType, ag.StartDate
FROM ACCOUNT_GEOGRAPHY ag
JOIN ACCOUNT a ON a.AccountID = ag.AccountID
WHERE ag.GeographyID = 1200
  AND ag.RelationshipType = 'PrimaryLocation';

-- Q07 Geographic-area-to-health-indicator retrieval by county FIPS.
-- Served by ix_geo_countyfips_partial and ix_obs_geo_ind_year.
SELECT g.CountyFIPS, g.GeographyName, hi.IndicatorName, ho.MeasureValue, ho.ObservationYear
FROM GEOGRAPHIC_AREA g
JOIN HEALTH_OBSERVATION ho ON ho.GeographyID = g.GeographyID
JOIN HEALTH_INDICATOR   hi ON hi.IndicatorID = ho.IndicatorID
WHERE g.CountyFIPS = '05119';

-- Q08 Account-to-regional-health-observation join. The signature hybrid
-- query. This is the path materialized by MV_ACCOUNT_REGIONAL_HEALTH_PROFILE.
SELECT a.AccountID, a.AccountName, g.CountyFIPS, g.GeographyName,
       hi.IndicatorName, hi.FactorCategory, ho.MeasureValue, ho.ObservationYear
FROM ACCOUNT a
JOIN ACCOUNT_GEOGRAPHY  ag ON ag.AccountID   = a.AccountID
JOIN GEOGRAPHIC_AREA     g ON g.GeographyID  = ag.GeographyID
JOIN HEALTH_OBSERVATION ho ON ho.GeographyID = g.GeographyID
JOIN HEALTH_INDICATOR   hi ON hi.IndicatorID = ho.IndicatorID
WHERE a.AccountID = 12;

-- Q09 Dataset-to-data-asset lineage lookup.
-- Served by ix_asset_dataset_type. Also the query the ML pipeline uses
-- to locate the DS010 unstructured document.
SELECT d.DatasetID, d.DatasetName, d.SourceOrganization,
       da.FileName, da.RelativePath, da.FileFormat, da.AssetType, da.SHA256
FROM DATASET d
JOIN DATA_ASSET da ON da.DatasetID = d.DatasetID
WHERE d.DatasetID = 'DS010'
  AND da.AssetType = 'unstructured document';

-- Q10 Quote status lookup: the open work queue.
-- Served by the partial index ix_quote_open_status.
SELECT q.QuoteID, q.QuoteNumber, q.CustomerID, q.ProductLine,
       q.QuoteStatus, q.RequestedDate, q.EstimatedPremium
FROM QUOTE q
WHERE q.QuoteStatus IN ('Draft','Submitted','Rated','Presented')
ORDER BY q.RequestedDate DESC
LIMIT 50;

-- Q11 Quote-to-contract conversion lookup, from the contract backwards.
-- Served by ix_conversion_contract.
SELECT qc.QuoteConversionID, qc.QuoteID, q.QuoteNumber, qc.ContractID,
       c.ContractNumber, qc.ConvertedAt, qc.ConversionStatus
FROM QUOTE_CONVERSION qc
JOIN QUOTE    q ON q.QuoteID    = qc.QuoteID
JOIN CONTRACT c ON c.ContractID = qc.ContractID
WHERE qc.ContractID = 301;

-- Q12 ML cluster-result lookup: all chunks in one cluster of one run.
-- Served by ix_mlcr_run_cluster.
SELECT mcr.ClusterID, mcr.DistanceToCentroid, dc.PageNumber, dc.WordCount,
       LEFT(dc.ChunkText, 120) AS chunk_preview
FROM ML_CLUSTER_RESULT mcr
JOIN DOCUMENT_CHUNK dc ON dc.DocumentChunkID = mcr.DocumentChunkID
WHERE mcr.MLRunID = 1
  AND mcr.ClusterID = 0
ORDER BY mcr.DistanceToCentroid;
