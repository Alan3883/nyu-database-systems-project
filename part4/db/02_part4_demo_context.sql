-- =====================================================================
-- Project Part IV - Demonstration service-area coverage
-- Target: PostgreSQL 16
--
-- WHAT THIS IS
--   Demonstration data only. It adds ACCOUNT_GEOGRAPHY rows of type
--   'ServiceArea' for the ten synthetic "Demo Account N" rows created by
--   scripts/load_curated_to_postgres.py.
--
-- WHY IT IS NEEDED
--   The Part II curated extract holds a 320-row sample of
--   HEALTH_OBSERVATION spread across 295 counties, so a county carries at
--   most three observations. The Part III loader gave each account one
--   primary county, which means one indicator per account: enough to
--   prove the join works, too thin to demonstrate a regional research
--   screen.
--
--   ACCOUNT_GEOGRAPHY already models this correctly. RelationshipType is
--   part of its primary key precisely because a group account operates in
--   more than one county. Adding service areas exercises the model as
--   designed rather than working around it.
--
-- WHAT IT DOES NOT DO
--   No observation, indicator, or geography row is invented. Every value
--   on the regional screen still comes from the curated public data
--   loaded in Part II. This script only states which counties a
--   demonstration account operates in.
--
-- Idempotent: re-running changes nothing.
-- =====================================================================

\echo 'Adding Part IV demonstration service areas...'

-- A service area must not repeat a county the account is already linked
-- to. MV_ACCOUNT_REGIONAL_HEALTH_PROFILE is unique on
-- (AccountID, GeographyID, IndicatorID, ObservationYear), so two
-- relationship types pointing at one county would produce duplicate view
-- rows and break CONCURRENTLY refresh.
INSERT INTO ACCOUNT_GEOGRAPHY (AccountID, GeographyID, RelationshipType, StartDate)
SELECT a.AccountID, g.GeographyID, 'ServiceArea', DATE '2021-01-01'
FROM ACCOUNT a
CROSS JOIN LATERAL (
    -- The counties carrying the most observations, deterministically
    -- offset per account so different accounts get different areas.
    SELECT ho.GeographyID
    FROM HEALTH_OBSERVATION ho
    WHERE NOT EXISTS (
        SELECT 1 FROM ACCOUNT_GEOGRAPHY ag
        WHERE ag.AccountID = a.AccountID
          AND ag.GeographyID = ho.GeographyID)
    GROUP BY ho.GeographyID
    ORDER BY count(*) DESC, ho.GeographyID
    OFFSET ((a.AccountID - 1) * 6) LIMIT 6
) g
WHERE a.AccountID BETWEEN 1 AND 10
  AND a.AccountName LIKE 'Demo Account %'
ON CONFLICT DO NOTHING;

REFRESH MATERIALIZED VIEW CONCURRENTLY MV_ACCOUNT_REGIONAL_HEALTH_PROFILE;
ANALYZE ACCOUNT_GEOGRAPHY;

\echo 'Part IV demonstration service areas applied.'
