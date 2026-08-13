-- =====================================================================
-- Project Part III - Roles and Least-Privilege Grants
-- Target: PostgreSQL 16
--
-- Four roles, each holding the smallest set of privileges that lets it
-- do its job. No role is granted SUPERUSER. No role owns the schema.
--
-- These are NOLOGIN group roles. Real login users are granted membership
-- and are created outside this file with passwords supplied from the
-- environment, so no credential appears in the repository.
-- =====================================================================

\echo 'Creating Part III roles and grants...'

-- ---------------------------------------------------------------------
-- Role definitions
-- ---------------------------------------------------------------------
DO $$
BEGIN
    -- Application role: runs the quote workflow. Reads reference data,
    -- writes quote and contract data.
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'insurance_app') THEN
        CREATE ROLE insurance_app NOLOGIN;
    END IF;

    -- Analyst role: read-only. Cannot change any business record.
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'insurance_analyst') THEN
        CREATE ROLE insurance_analyst NOLOGIN;
    END IF;

    -- ML writer role: writes model runs, chunks, and results only.
    -- Deliberately has no write access to any insurance table.
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ml_writer') THEN
        CREATE ROLE ml_writer NOLOGIN;
    END IF;

    -- Loader role: bulk-loads curated data and refreshes the view.
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'data_loader') THEN
        CREATE ROLE data_loader NOLOGIN;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO insurance_app, insurance_analyst, ml_writer, data_loader;

-- ---------------------------------------------------------------------
-- insurance_analyst : SELECT only, everywhere.
-- ---------------------------------------------------------------------
GRANT SELECT ON ALL TABLES IN SCHEMA public TO insurance_analyst;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO insurance_analyst;

-- ---------------------------------------------------------------------
-- insurance_app : read reference data, write transactional data.
-- ---------------------------------------------------------------------
GRANT SELECT ON ALL TABLES IN SCHEMA public TO insurance_app;

GRANT SELECT, INSERT, UPDATE ON
    QUOTE, QUOTE_COVERAGE, QUOTE_RISK_FACTOR, PAYMENT_AUTHORIZATION,
    CONTRACT, CONTRACT_BENEFIT, CONTRACT_PREMIUM,
    CUSTOMER, ACCOUNT
TO insurance_app;

-- Append-only tables: insert and select, no update, no delete. This is
-- what makes the audit trail trustworthy.
GRANT SELECT, INSERT ON QUOTE_STATUS_HISTORY, QUOTE_CONVERSION TO insurance_app;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO insurance_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO insurance_app;

-- ---------------------------------------------------------------------
-- ml_writer : ML tables only.
--
-- Reads DATASET and DATA_ASSET to locate DS010, reads nothing else from
-- the insurance side, and cannot write to any insurance table. This
-- enforces the boundary that model output never reaches a customer
-- record by accident.
-- ---------------------------------------------------------------------
GRANT SELECT ON DATASET, DATA_ASSET, GEOGRAPHIC_AREA, HEALTH_INDICATOR, HEALTH_OBSERVATION TO ml_writer;
GRANT SELECT, INSERT, UPDATE ON ML_RUN, DOCUMENT_CHUNK, ML_CLUSTER_RESULT, ML_CLUSTER_SUMMARY TO ml_writer;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ml_writer;

-- ---------------------------------------------------------------------
-- data_loader : bulk load of hybrid/reference tables + view refresh.
-- ---------------------------------------------------------------------
GRANT SELECT, INSERT, UPDATE, DELETE ON
    DATASET, DATA_ASSET, GEOGRAPHIC_AREA, HEALTH_INDICATOR, HEALTH_OBSERVATION, ACCOUNT_GEOGRAPHY
TO data_loader;
GRANT SELECT ON MV_ACCOUNT_REGIONAL_HEALTH_PROFILE TO data_loader, insurance_analyst, insurance_app;

-- ---------------------------------------------------------------------
-- Explicit denial of the destructive path.
--
-- No role is granted DELETE on the insurance transactional tables.
-- Cancelling a contract is a status change, not a row deletion, which
-- preserves history. Physical deletion is an administrator action.
-- ---------------------------------------------------------------------

-- Column-level restriction: SSN_TIN is the most sensitive column in the
-- model. Analysts get every other CUSTOMER column but not this one.
REVOKE SELECT ON CUSTOMER FROM insurance_analyst;
GRANT SELECT (CustomerID, CustLastName, CustFirstName, CustDOB, CustomerType, Status)
    ON CUSTOMER TO insurance_analyst;

COMMENT ON ROLE insurance_analyst IS
    'Read-only reporting role. No access to CUSTOMER.SSN_TIN.';
COMMENT ON ROLE ml_writer IS
    'ML pipeline role. Cannot write to any insurance table.';

\echo 'Part III roles and grants created.'
