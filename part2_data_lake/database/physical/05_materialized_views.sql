-- =====================================================================
-- Project Part III - Selective Materialization
-- Target: PostgreSQL 16
--
-- "Selective materialization" is the fourth technique named by the
-- assignment. It is applied here to exactly one query path: the
-- five-table hybrid join that is the signature of this project.
--
-- WHY THIS PATH
--   ACCOUNT -> ACCOUNT_GEOGRAPHY -> GEOGRAPHIC_AREA
--           -> HEALTH_OBSERVATION -> HEALTH_INDICATOR
--   It joins five tables, it is read by every regional review, and its
--   inputs change only when a curated data load runs. High read
--   frequency plus low write frequency is the textbook case for a
--   materialized view.
--
-- WHY NOT A PLAIN VIEW
--   A plain view re-executes the five-way join on every call. The join
--   cost is paid by every reader. Materializing pays it once per load.
--
-- IMPORTANT SCOPE NOTE
--   This view carries REGIONAL AGGREGATE context only. It describes the
--   county an account sits in. It does not describe any person, and it
--   must not be read as individual medical risk. See
--   architecture/governance/model_governance.md.
-- =====================================================================

\echo 'Creating Part III materialized view...'

DROP MATERIALIZED VIEW IF EXISTS MV_ACCOUNT_REGIONAL_HEALTH_PROFILE CASCADE;

CREATE MATERIALIZED VIEW MV_ACCOUNT_REGIONAL_HEALTH_PROFILE AS
SELECT
    a.AccountID,
    a.AccountName,
    a.State                AS AccountState,
    g.GeographyID,
    g.CountyFIPS,
    g.GeographyName,
    g.StateCode            AS GeographyStateCode,
    hi.IndicatorID,
    hi.IndicatorName,
    hi.DiseaseCategory,
    hi.FactorCategory,
    ho.ObservationYear,
    ho.MeasureValue,
    hi.Unit,
    ho.DatasetID           AS SourceDatasetID,
    ag.RelationshipType    AS AccountGeographyRelationship,
    now()                  AS LastRefreshedAt
FROM ACCOUNT a
JOIN ACCOUNT_GEOGRAPHY  ag ON ag.AccountID   = a.AccountID
JOIN GEOGRAPHIC_AREA     g ON g.GeographyID  = ag.GeographyID
JOIN HEALTH_OBSERVATION ho ON ho.GeographyID = g.GeographyID
JOIN HEALTH_INDICATOR   hi ON hi.IndicatorID = ho.IndicatorID
WHERE ag.EndDate IS NULL OR ag.EndDate >= CURRENT_DATE;

COMMENT ON MATERIALIZED VIEW MV_ACCOUNT_REGIONAL_HEALTH_PROFILE IS
    'Pre-joined account-to-regional-health context. Regional aggregate only; not individual medical risk. Refresh after each curated data load.';

-- ---------------------------------------------------------------------
-- Supporting indexes on the materialized view.
--
-- A UNIQUE index is required for REFRESH MATERIALIZED VIEW CONCURRENTLY.
-- Without it, every refresh takes an exclusive lock and blocks readers.
-- The combination below is unique because one account/area pair holds at
-- most one observation per indicator per year.
-- ---------------------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_arhp_identity
    ON MV_ACCOUNT_REGIONAL_HEALTH_PROFILE
       (AccountID, GeographyID, IndicatorID, ObservationYear);

-- Access path: "give me this account's regional profile".
CREATE INDEX IF NOT EXISTS ix_mv_arhp_account
    ON MV_ACCOUNT_REGIONAL_HEALTH_PROFILE (AccountID);

-- Access path: "compare this indicator across counties".
CREATE INDEX IF NOT EXISTS ix_mv_arhp_fips_indicator
    ON MV_ACCOUNT_REGIONAL_HEALTH_PROFILE (CountyFIPS, IndicatorID);

-- Access path: portfolio review filtered by factor category.
CREATE INDEX IF NOT EXISTS ix_mv_arhp_factor
    ON MV_ACCOUNT_REGIONAL_HEALTH_PROFILE (FactorCategory);

ANALYZE MV_ACCOUNT_REGIONAL_HEALTH_PROFILE;

-- ---------------------------------------------------------------------
-- REFRESH STRATEGY
--
-- Trigger : after each curated data load (script 03_build_curated_data.py)
--           and after any ACCOUNT_GEOGRAPHY change.
-- Cadence : the underlying public datasets publish annually, so a
--           scheduled monthly refresh is more than sufficient. The load
--           event, not the clock, is the real trigger.
-- Method  : CONCURRENTLY, so readers are not blocked. This requires the
--           unique index above and cannot run inside a transaction block.
-- Cost    : full recomputation of the five-way join. At current volumes
--           this is well under a second.
--
-- Command:
--   REFRESH MATERIALIZED VIEW CONCURRENTLY MV_ACCOUNT_REGIONAL_HEALTH_PROFILE;
--
-- First population after creation must be non-concurrent:
--   REFRESH MATERIALIZED VIEW MV_ACCOUNT_REGIONAL_HEALTH_PROFILE;
-- ---------------------------------------------------------------------

-- ---------------------------------------------------------------------
-- VALIDATION QUERY
-- Confirms the materialized view agrees with the live join it replaces.
-- Any nonzero difference means the view is stale and needs a refresh.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW V_MV_ARHP_VALIDATION AS
WITH live AS (
    SELECT count(*) AS live_rows
    FROM ACCOUNT a
    JOIN ACCOUNT_GEOGRAPHY  ag ON ag.AccountID   = a.AccountID
    JOIN GEOGRAPHIC_AREA     g ON g.GeographyID  = ag.GeographyID
    JOIN HEALTH_OBSERVATION ho ON ho.GeographyID = g.GeographyID
    JOIN HEALTH_INDICATOR   hi ON hi.IndicatorID = ho.IndicatorID
    WHERE ag.EndDate IS NULL OR ag.EndDate >= CURRENT_DATE
),
mv AS (
    SELECT count(*) AS mv_rows FROM MV_ACCOUNT_REGIONAL_HEALTH_PROFILE
)
SELECT live.live_rows,
       mv.mv_rows,
       live.live_rows - mv.mv_rows AS difference,
       CASE WHEN live.live_rows = mv.mv_rows THEN 'IN SYNC' ELSE 'STALE - REFRESH REQUIRED' END AS status
FROM live, mv;

COMMENT ON VIEW V_MV_ARHP_VALIDATION IS
    'Compares materialized view row count against the live join. Used by database tests.';

\echo 'Part III materialized view created.'
