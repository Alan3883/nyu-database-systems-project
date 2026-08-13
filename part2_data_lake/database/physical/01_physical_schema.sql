-- =====================================================================
-- Project Part III - Physical Schema Layer
-- Target: PostgreSQL 16
-- Author: Alan Mo (bm3883)
--
-- This file applies physical-design decisions on top of the Part II
-- logical schema (logical_model/logical_schema.sql). It does NOT
-- recreate the 26 Part II tables. Load the Part II schema first.
--
-- Decisions applied here:
--   1. PostgreSQL-specific types where they add value.
--   2. Audit timestamps on tables that Part III will write to.
--   3. Storage and fillfactor choices for update-heavy tables.
--   4. Statistics targets for columns used in selective predicates.
--
-- Every change is additive. No Part II column is dropped or renamed.
-- =====================================================================

\echo 'Applying Part III physical schema layer...'

-- ---------------------------------------------------------------------
-- 1. Identity / surrogate key strategy
--
-- Part II declared surrogate keys as plain INTEGER with values supplied
-- by the loader. For tables that Part III inserts into at runtime we
-- attach sequences so the application does not have to compute keys.
-- Existing Part II tables keep their loaded values; the sequence is set
-- past the current maximum so new inserts never collide.
-- ---------------------------------------------------------------------

CREATE SEQUENCE IF NOT EXISTS seq_account_id      AS BIGINT START 1;
CREATE SEQUENCE IF NOT EXISTS seq_customer_id     AS BIGINT START 1;
CREATE SEQUENCE IF NOT EXISTS seq_contract_id     AS BIGINT START 1;
CREATE SEQUENCE IF NOT EXISTS seq_benefit_id      AS BIGINT START 1;
CREATE SEQUENCE IF NOT EXISTS seq_premium_id      AS BIGINT START 1;

-- Advance each sequence past any data already loaded.
SELECT setval('seq_account_id',  COALESCE((SELECT MAX(AccountID)  FROM ACCOUNT), 0) + 1, false);
SELECT setval('seq_customer_id', COALESCE((SELECT MAX(CustomerID) FROM CUSTOMER), 0) + 1, false);
SELECT setval('seq_contract_id', COALESCE((SELECT MAX(ContractID) FROM CONTRACT), 0) + 1, false);
SELECT setval('seq_benefit_id',  COALESCE((SELECT MAX(BenefitID)  FROM CONTRACT_BENEFIT), 0) + 1, false);
SELECT setval('seq_premium_id',  COALESCE((SELECT MAX(PremiumID)  FROM CONTRACT_PREMIUM), 0) + 1, false);

-- ---------------------------------------------------------------------
-- 2. Audit timestamps
--
-- Part II tables carry business dates (StartDate/EndDate) but no row
-- audit columns. Part III adds CreatedAt/UpdatedAt to the tables that
-- the quote workflow writes to, so a row's technical history can be
-- separated from its business validity period.
--
-- Choice: timestamptz, not timestamp. The insurer operates across time
-- zones and timestamptz stores an unambiguous instant.
-- ---------------------------------------------------------------------

ALTER TABLE ACCOUNT   ADD COLUMN IF NOT EXISTS CreatedAt TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE ACCOUNT   ADD COLUMN IF NOT EXISTS UpdatedAt TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE CUSTOMER  ADD COLUMN IF NOT EXISTS CreatedAt TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE CUSTOMER  ADD COLUMN IF NOT EXISTS UpdatedAt TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE CONTRACT  ADD COLUMN IF NOT EXISTS CreatedAt TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE CONTRACT  ADD COLUMN IF NOT EXISTS UpdatedAt TIMESTAMPTZ NOT NULL DEFAULT now();

-- A single shared trigger function keeps UpdatedAt current. This is the
-- one piece of procedural code in the design; it replaces per-table
-- application logic and cannot be bypassed by a direct SQL update.
CREATE OR REPLACE FUNCTION trg_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.UpdatedAt := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS set_updated_at ON ACCOUNT;
CREATE TRIGGER set_updated_at BEFORE UPDATE ON ACCOUNT
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

DROP TRIGGER IF EXISTS set_updated_at ON CUSTOMER;
CREATE TRIGGER set_updated_at BEFORE UPDATE ON CUSTOMER
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

DROP TRIGGER IF EXISTS set_updated_at ON CONTRACT;
CREATE TRIGGER set_updated_at BEFORE UPDATE ON CONTRACT
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

-- ---------------------------------------------------------------------
-- 3. Fillfactor for update-heavy tables
--
-- Default fillfactor is 100, which packs pages full. Rows that are
-- updated then have to move to another page, which also forces every
-- index on the table to be updated. Lowering fillfactor leaves free
-- space on each page so PostgreSQL can use a heap-only tuple (HOT)
-- update and skip the index maintenance.
--
-- Applied only to tables whose rows change after insert:
--   ACCOUNT / CUSTOMER / CONTRACT  - status and address changes
-- Not applied to HEALTH_OBSERVATION, which is insert-only reference data.
-- ---------------------------------------------------------------------

ALTER TABLE ACCOUNT  SET (fillfactor = 90);
ALTER TABLE CUSTOMER SET (fillfactor = 90);
ALTER TABLE CONTRACT SET (fillfactor = 90);

-- ---------------------------------------------------------------------
-- 4. Statistics targets
--
-- PostgreSQL keeps 100 histogram buckets per column by default. Columns
-- used in selective filters across many distinct values benefit from a
-- finer histogram, which produces better row estimates and better plans.
--
-- CountyFIPS has ~3,144 distinct values; the default histogram is too
-- coarse and leads the planner to misjudge selectivity on FIPS lookups.
-- ---------------------------------------------------------------------

ALTER TABLE GEOGRAPHIC_AREA    ALTER COLUMN CountyFIPS      SET STATISTICS 500;
ALTER TABLE HEALTH_OBSERVATION ALTER COLUMN GeographyID     SET STATISTICS 300;
ALTER TABLE HEALTH_OBSERVATION ALTER COLUMN IndicatorID     SET STATISTICS 300;

-- ---------------------------------------------------------------------
-- 5. Data-type refinement
--
-- SHA256 in DATA_ASSET is CHAR(64), which is correct and fixed width.
-- FileSizeBytes is BIGINT, correct for large files.
-- MeasureValue is NUMERIC(12,4): exact decimal, not floating point.
-- These Part II choices are already appropriate and are retained.
--
-- One refinement: DATA_ASSET.CloudURI is widened because a full GCS URI
-- with a long prefix can exceed the original 500-character allowance
-- once the part3/ hierarchy is added.
-- ---------------------------------------------------------------------

ALTER TABLE DATA_ASSET ALTER COLUMN CloudURI TYPE VARCHAR(1000);

-- ---------------------------------------------------------------------
-- 6. Table comments recording physical intent
-- ---------------------------------------------------------------------

COMMENT ON COLUMN ACCOUNT.CreatedAt IS
    'Row creation instant. Technical audit column, distinct from business StartDate.';
COMMENT ON COLUMN ACCOUNT.UpdatedAt IS
    'Row last-modified instant, maintained by trigger set_updated_at.';

\echo 'Part III physical schema layer applied.'
