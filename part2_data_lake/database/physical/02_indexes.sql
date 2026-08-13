-- =====================================================================
-- Project Part III - Index Strategy
-- Target: PostgreSQL 16
--
-- Run AFTER 03_workflow_extension.sql and 04_ml_metadata_extension.sql
-- because several indexes below are on Part III tables.
--
-- RULE APPLIED: an index is created only when a query in
-- database/queries/operational_workload.sql or analytical_workload.sql
-- needs it. No index is created "just in case", because every index
-- adds cost to INSERT, UPDATE, and DELETE and consumes storage.
--
-- Part II already created 23 secondary indexes on foreign keys. Those
-- are not repeated here. This file adds only what the Part III workload
-- requires: composite indexes, partial indexes, and covering indexes.
--
-- Each index carries a comment block:
--   Query      - the workload query it serves
--   Benefit    - expected read improvement
--   Cost       - write overhead
--   Reason     - why this shape and this column order
-- =====================================================================

\echo 'Creating Part III indexes...'

-- ---------------------------------------------------------------------
-- HYBRID ANALYTICAL PATH
-- ---------------------------------------------------------------------

-- Query   : Q08 account-to-regional-health-observation join,
--           Q13 regional indicator aggregation
-- Benefit : Replaces a sequential scan of HEALTH_OBSERVATION plus a
--           separate filter with one index range scan. GeographyID is
--           the join column from GEOGRAPHIC_AREA, so it leads.
-- Cost    : One extra index on an insert-only reference table. Loads are
--           bulk and infrequent, so the write cost is negligible.
-- Reason  : Column order is (GeographyID, IndicatorID, ObservationYear).
--           GeographyID first because every hybrid query filters or joins
--           on it. IndicatorID second because indicator filters are the
--           next most common. ObservationYear last because it is usually
--           a range or is only projected, and a trailing range column
--           still allows the leading equality columns to be used.
CREATE INDEX IF NOT EXISTS ix_obs_geo_ind_year
    ON HEALTH_OBSERVATION (GeographyID, IndicatorID, ObservationYear);

-- Query   : Q13 regional indicator aggregation with MeasureValue
-- Benefit : Index-only scan. MeasureValue is carried in the INCLUDE
--           payload so the aggregate never touches the heap.
-- Cost    : Slightly wider index pages than a plain 2-column index.
-- Reason  : INCLUDE puts the value in the leaf without making it part of
--           the search key, which is exactly the covering-index case.
CREATE INDEX IF NOT EXISTS ix_obs_ind_geo_covering
    ON HEALTH_OBSERVATION (IndicatorID, GeographyID) INCLUDE (MeasureValue, ObservationYear);

-- Query   : Q06 account-to-geographic-area retrieval
-- Benefit : ACCOUNT_GEOGRAPHY has a composite primary key beginning with
--           AccountID, so account-side lookups are already covered. This
--           index serves the reverse direction: given an area, find the
--           accounts in it. Part II created ix_account_geography_geo on
--           GeographyID alone; this replaces it with a form that also
--           carries the relationship type and dates.
-- Cost    : One index on a small associative table.
-- Reason  : (GeographyID, RelationshipType) matches the predicate pair
--           used when reviewing a region's book of business.
CREATE INDEX IF NOT EXISTS ix_acctgeo_geo_type
    ON ACCOUNT_GEOGRAPHY (GeographyID, RelationshipType) INCLUDE (StartDate, EndDate);

-- Query   : Q07 geographic-area-to-health-indicator retrieval by FIPS
-- Benefit : Direct lookup on the five-digit county FIPS code, the common
--           public-data join key. Partial: only county rows have a FIPS
--           value, so nation and state rows are excluded from the index.
-- Cost    : Smaller than a full index because ~3,144 of 3,196 rows qualify
--           and NULLs are skipped.
-- Reason  : Partial index keeps the structure focused on the only rows
--           that can ever match a FIPS predicate.
CREATE INDEX IF NOT EXISTS ix_geo_countyfips_partial
    ON GEOGRAPHIC_AREA (CountyFIPS)
    WHERE CountyFIPS IS NOT NULL;

-- ---------------------------------------------------------------------
-- CORE INSURANCE LOOKUPS
-- ---------------------------------------------------------------------

-- Query   : Q04 account-to-contract retrieval for active contracts only
-- Benefit : Partial index containing only active rows. In a mature book
--           most contracts are terminated, so restricting the index to
--           active rows keeps it small and cache-resident.
-- Cost    : Rows leaving 'Active' status cause an index delete.
-- Reason  : Status = 'Active' is the dominant predicate in operational
--           screens; the partial predicate must appear in the query for
--           the planner to use the index.
CREATE INDEX IF NOT EXISTS ix_contract_account_active
    ON CONTRACT (AccountID, EffectiveDate DESC)
    WHERE Status = 'Active';

-- Query   : Q05 associate-to-contract retrieval via manager contract
-- Benefit : Supports the premium-credit path from MANAGER_CONTRACT into
--           CONTRACT_PREMIUM without scanning the premium table.
-- Cost    : One index on a transactional table with moderate insert rate.
-- Reason  : (ManagerContractID, YearNumber) matches production-credit
--           reporting, which is always scoped to a year.
CREATE INDEX IF NOT EXISTS ix_premium_mgr_year
    ON CONTRACT_PREMIUM (ManagerContractID, YearNumber)
    WHERE ManagerContractID IS NOT NULL;

-- Query   : Q02 customer lookup by name
-- Benefit : Supports surname-then-forename lookup, the normal service
--           desk access pattern.
-- Cost    : One index on a table with low update frequency.
-- Reason  : Composite in (last, first) order because the surname is
--           always supplied and the forename narrows it.
CREATE INDEX IF NOT EXISTS ix_customer_name
    ON CUSTOMER (CustLastName, CustFirstName);

-- ---------------------------------------------------------------------
-- LINEAGE
-- ---------------------------------------------------------------------

-- Query   : Q09 dataset-to-data-asset lineage lookup
-- Benefit : Groups a dataset's files by type in one index scan.
-- Cost    : Negligible; DATA_ASSET holds 10 rows and grows slowly.
-- Reason  : (DatasetID, AssetType) matches "which files of which kind
--           belong to this dataset", including the unstructured filter
--           used by the ML pipeline to find DS010.
CREATE INDEX IF NOT EXISTS ix_asset_dataset_type
    ON DATA_ASSET (DatasetID, AssetType);

-- ---------------------------------------------------------------------
-- QUOTE WORKFLOW
-- ---------------------------------------------------------------------

-- Query   : Q10 quote status lookup for open work
-- Benefit : Partial index over open quotes only. Closed quotes
--           (Converted, Rejected, Expired) accumulate indefinitely and
--           are never in a work queue, so excluding them keeps the index
--           proportional to active workload rather than to history.
-- Cost    : A quote leaving an open state causes one index delete.
-- Reason  : This is the clearest partial-index case in the design: the
--           hot subset is small and permanently bounded.
CREATE INDEX IF NOT EXISTS ix_quote_open_status
    ON QUOTE (QuoteStatus, RequestedDate DESC)
    WHERE QuoteStatus IN ('Draft','Submitted','Rated','Presented');

-- Query   : Q10 quote lookup by customer
-- Benefit : Retrieves a customer's quote history newest first.
-- Cost    : One index on a moderate-insert table.
-- Reason  : DESC on RequestedDate matches the display order, letting the
--           index satisfy the ORDER BY without a sort step.
CREATE INDEX IF NOT EXISTS ix_quote_customer_date
    ON QUOTE (CustomerID, RequestedDate DESC);

-- Query   : Q11 quote-to-contract conversion lookup
-- Benefit : Finds the quote behind a contract. UNIQUE(QuoteID) already
--           indexes the quote side, so this covers the contract side.
-- Cost    : One small index.
-- Reason  : Conversion audits run from the contract backwards.
CREATE INDEX IF NOT EXISTS ix_conversion_contract
    ON QUOTE_CONVERSION (ContractID);

-- Query   : Q10 status history for a quote
-- Benefit : Returns a quote's transitions in chronological order without
--           a sort.
-- Cost    : One index on an append-only table.
-- Reason  : (QuoteID, ChangedAt) is both the access path and the display
--           order.
CREATE INDEX IF NOT EXISTS ix_qsh_quote_time
    ON QUOTE_STATUS_HISTORY (QuoteID, ChangedAt);

-- ---------------------------------------------------------------------
-- ML RESULTS
-- ---------------------------------------------------------------------

-- Query   : Q12 ML cluster-result lookup
-- Benefit : Retrieves all chunks in one cluster of one run. The primary
--           key is (MLRunID, DocumentChunkID), which cannot serve a
--           cluster-first predicate, so this index is required.
-- Cost    : One index on a table written once per run.
-- Reason  : (MLRunID, ClusterID) is the natural review access pattern:
--           "show me everything in cluster 2 of this run".
CREATE INDEX IF NOT EXISTS ix_mlcr_run_cluster
    ON ML_CLUSTER_RESULT (MLRunID, ClusterID) INCLUDE (DistanceToCentroid);

-- Query   : Q12 chunk-to-cluster reverse lookup
-- Benefit : Given a chunk, find which clusters it landed in across runs.
--           Used to compare model versions.
-- Cost    : One index.
-- Reason  : Supports model-stability comparison between runs.
CREATE INDEX IF NOT EXISTS ix_mlcr_chunk
    ON ML_CLUSTER_RESULT (DocumentChunkID);

-- Query   : Q12 chunk retrieval by source page
-- Benefit : Traces a cluster finding back to the page in the PDF.
-- Cost    : One index on a table written once per extraction.
-- Reason  : (DataAssetID, PageNumber) is the traceability path required
--           by the data lineage governance document.
CREATE INDEX IF NOT EXISTS ix_chunk_asset_page
    ON DOCUMENT_CHUNK (DataAssetID, PageNumber);

-- Query   : Q14 dataset and model-run audit lookup
-- Benefit : Finds runs for a dataset in reverse chronological order.
-- Cost    : Negligible; ML_RUN grows one row per training run.
-- Reason  : Audit queries always start from "the most recent run".
CREATE INDEX IF NOT EXISTS ix_mlrun_dataset_started
    ON ML_RUN (TrainingDatasetID, StartedAt DESC);

-- ---------------------------------------------------------------------
-- Refresh planner statistics so the new indexes are costed correctly.
-- ---------------------------------------------------------------------
ANALYZE;

\echo 'Part III indexes created.'
