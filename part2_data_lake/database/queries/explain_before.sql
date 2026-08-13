-- =====================================================================
-- Part III - Baseline query plans BEFORE physical optimization
--
-- Captured with the Part II schema and its 23 foreign-key indexes only.
-- No Part III index, materialized view, or workflow table existed yet.
--
-- Reproduce with:
--   python3 scripts/run_performance_tests.py --phase before
-- Captured output: database/evidence/explain_before_output.txt
-- =====================================================================

EXPLAIN (ANALYZE, BUFFERS)
SELECT AccountID, AccountName, AccountType, Status FROM ACCOUNT
WHERE AccountName='Demo Account 7' AND Address1='7 Main St' AND City='City7'
  AND State='AR' AND Zip='70007' AND CompanyCode='DEMO7';

EXPLAIN (ANALYZE, BUFFERS)
SELECT CustomerID, CustLastName, CustFirstName FROM CUSTOMER WHERE CustLastName='Last42';

EXPLAIN (ANALYZE, BUFFERS)
SELECT ContractID, ContractNumber, AccountID, PlanName FROM CONTRACT
WHERE ContractNumber='C-000123';

EXPLAIN (ANALYZE, BUFFERS)
SELECT ContractID, ContractNumber, PlanName, EffectiveDate FROM CONTRACT
WHERE AccountID=12 AND Status='Active' ORDER BY EffectiveDate DESC;

EXPLAIN (ANALYZE, BUFFERS)
SELECT g.CountyFIPS, g.GeographyName, hi.IndicatorName, ho.MeasureValue
FROM GEOGRAPHIC_AREA g
JOIN HEALTH_OBSERVATION ho ON ho.GeographyID=g.GeographyID
JOIN HEALTH_INDICATOR hi ON hi.IndicatorID=ho.IndicatorID
WHERE g.CountyFIPS='05119';

-- The signature five-table hybrid join, before materialization.
EXPLAIN (ANALYZE, BUFFERS)
SELECT a.AccountID, a.AccountName, g.CountyFIPS, hi.IndicatorName, ho.MeasureValue
FROM ACCOUNT a
JOIN ACCOUNT_GEOGRAPHY ag ON ag.AccountID=a.AccountID
JOIN GEOGRAPHIC_AREA g ON g.GeographyID=ag.GeographyID
JOIN HEALTH_OBSERVATION ho ON ho.GeographyID=g.GeographyID
JOIN HEALTH_INDICATOR hi ON hi.IndicatorID=ho.IndicatorID
WHERE a.AccountID=12;

EXPLAIN (ANALYZE, BUFFERS)
SELECT hi.IndicatorName, g.StateCode, count(*) AS n, avg(ho.MeasureValue) AS avg_v
FROM HEALTH_OBSERVATION ho
JOIN HEALTH_INDICATOR hi ON hi.IndicatorID=ho.IndicatorID
JOIN GEOGRAPHIC_AREA g ON g.GeographyID=ho.GeographyID
WHERE hi.FactorCategory='Disease outcome'
GROUP BY hi.IndicatorName, g.StateCode ORDER BY avg_v DESC LIMIT 25;
