-- =====================================================================
-- Project Part III - Rollback
-- Target: PostgreSQL 16
--
-- Removes every object created by Part III and leaves the 26 Part II
-- tables and their data intact. Use this to return the database to its
-- end-of-Part-II state.
--
-- Order matters: dependent objects first.
-- =====================================================================

\echo 'Rolling back Part III objects...'

-- 1. Views and materialized views
DROP VIEW IF EXISTS V_MV_ARHP_VALIDATION CASCADE;
DROP MATERIALIZED VIEW IF EXISTS MV_ACCOUNT_REGIONAL_HEALTH_PROFILE CASCADE;

-- 2. ML extension (child tables first)
DROP TABLE IF EXISTS ML_CLUSTER_SUMMARY CASCADE;
DROP TABLE IF EXISTS ML_CLUSTER_RESULT CASCADE;
DROP TABLE IF EXISTS DOCUMENT_CHUNK CASCADE;
DROP TABLE IF EXISTS ML_RUN CASCADE;

-- 3. Workflow extension (child tables first)
DROP TABLE IF EXISTS QUOTE_CONVERSION CASCADE;
DROP TABLE IF EXISTS PAYMENT_AUTHORIZATION CASCADE;
DROP TABLE IF EXISTS QUOTE_STATUS_HISTORY CASCADE;
DROP TABLE IF EXISTS QUOTE_RISK_FACTOR CASCADE;
DROP TABLE IF EXISTS QUOTE_COVERAGE CASCADE;
DROP TABLE IF EXISTS QUOTE CASCADE;

-- 4. Synthetic performance table (never part of the data lake)
DROP TABLE IF EXISTS perf_health_observation_synthetic CASCADE;

-- 5. Part III indexes on Part II tables
DROP INDEX IF EXISTS ix_obs_geo_ind_year;
DROP INDEX IF EXISTS ix_obs_ind_geo_covering;
DROP INDEX IF EXISTS ix_acctgeo_geo_type;
DROP INDEX IF EXISTS ix_geo_countyfips_partial;
DROP INDEX IF EXISTS ix_contract_account_active;
DROP INDEX IF EXISTS ix_premium_mgr_year;
DROP INDEX IF EXISTS ix_customer_name;
DROP INDEX IF EXISTS ix_asset_dataset_type;

-- 6. Triggers and trigger function
DROP TRIGGER IF EXISTS set_updated_at ON ACCOUNT;
DROP TRIGGER IF EXISTS set_updated_at ON CUSTOMER;
DROP TRIGGER IF EXISTS set_updated_at ON CONTRACT;
DROP FUNCTION IF EXISTS trg_set_updated_at();

-- 7. Audit columns added by Part III
ALTER TABLE ACCOUNT  DROP COLUMN IF EXISTS CreatedAt;
ALTER TABLE ACCOUNT  DROP COLUMN IF EXISTS UpdatedAt;
ALTER TABLE CUSTOMER DROP COLUMN IF EXISTS CreatedAt;
ALTER TABLE CUSTOMER DROP COLUMN IF EXISTS UpdatedAt;
ALTER TABLE CONTRACT DROP COLUMN IF EXISTS CreatedAt;
ALTER TABLE CONTRACT DROP COLUMN IF EXISTS UpdatedAt;

-- 8. Storage parameters back to defaults
ALTER TABLE ACCOUNT  RESET (fillfactor);
ALTER TABLE CUSTOMER RESET (fillfactor);
ALTER TABLE CONTRACT RESET (fillfactor);

ALTER TABLE GEOGRAPHIC_AREA    ALTER COLUMN CountyFIPS  SET STATISTICS -1;
ALTER TABLE HEALTH_OBSERVATION ALTER COLUMN GeographyID SET STATISTICS -1;
ALTER TABLE HEALTH_OBSERVATION ALTER COLUMN IndicatorID SET STATISTICS -1;

-- 9. Sequences
DROP SEQUENCE IF EXISTS seq_account_id;
DROP SEQUENCE IF EXISTS seq_customer_id;
DROP SEQUENCE IF EXISTS seq_contract_id;
DROP SEQUENCE IF EXISTS seq_benefit_id;
DROP SEQUENCE IF EXISTS seq_premium_id;

-- 10. Roles (revoke before dropping)
DO $$
DECLARE r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['insurance_app','insurance_analyst','ml_writer','data_loader'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM %I', r);
            EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM %I', r);
            EXECUTE format('REVOKE ALL ON SCHEMA public FROM %I', r);
            EXECUTE format('DROP ROLE %I', r);
        END IF;
    END LOOP;
END
$$;

-- Note: DATA_ASSET.CloudURI stays VARCHAR(1000). Narrowing it could
-- truncate stored URIs, so the widening is intentionally not reversed.

\echo 'Part III rollback complete. The 26 Part II tables are unchanged.'
