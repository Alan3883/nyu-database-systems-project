-- =====================================================================
-- Project Part III - Workflow Constraint Tests
-- Target: PostgreSQL 16
--
-- Each test asserts that the database rejects an invalid state. A test
-- "passes" when the constraint fires. Run with:
--   psql -d part3 -f workflow_constraint_tests.sql
-- =====================================================================

\set ON_ERROR_STOP off
\echo '=== Quote-to-contract workflow constraint tests ==='

-- ---------------------------------------------------------------------
-- Seed a realistic quote lifecycle. Customers and accounts already exist.
-- ---------------------------------------------------------------------
\echo ''
\echo '--- Seeding quote workflow data ---'

TRUNCATE QUOTE_CONVERSION, PAYMENT_AUTHORIZATION, QUOTE_STATUS_HISTORY,
         QUOTE_RISK_FACTOR, QUOTE_COVERAGE, QUOTE RESTART IDENTITY CASCADE;

INSERT INTO QUOTE (QuoteNumber, CustomerID, AccountID, ProductLine, QuoteStatus,
                   RequestedDate, EffectiveDate, ExpirationDate, EstimatedPremium)
SELECT 'Q-' || LPAD(gs::text, 6, '0'),
       ((gs - 1) % 200) + 1,
       ((gs - 1) % 50) + 1,
       CASE WHEN gs % 3 = 0 THEN 'A&H' WHEN gs % 3 = 1 THEN 'Life' ELSE 'FSA' END,
       CASE (gs % 6)
            WHEN 0 THEN 'Draft'     WHEN 1 THEN 'Submitted'
            WHEN 2 THEN 'Rated'     WHEN 3 THEN 'Presented'
            WHEN 4 THEN 'Accepted'  ELSE 'Rejected' END,
       DATE '2026-01-01' + (gs % 180),
       DATE '2026-03-01' + (gs % 90),
       DATE '2026-12-31',
       round((1200 + (gs % 400) * 7.5)::numeric, 2)
FROM generate_series(1, 120) gs;

INSERT INTO QUOTE_COVERAGE (QuoteID, CoverageName, CoverageLimit, Deductible, ProposedPremium)
SELECT q.QuoteID, 'Base Medical', 500000, 2500, q.EstimatedPremium * 0.7 FROM QUOTE q
UNION ALL
SELECT q.QuoteID, 'Dental Rider', 25000, 250, q.EstimatedPremium * 0.3 FROM QUOTE q
WHERE q.QuoteID % 2 = 0;

-- Risk factors, including regional aggregate context sourced from the
-- hybrid model. Note SourceReference points at a GEOGRAPHIC_AREA, never
-- at a person.
INSERT INTO QUOTE_RISK_FACTOR (QuoteID, RiskFactorType, SourceType, SourceReference,
                               FactorValue, ReviewStatus)
SELECT q.QuoteID, 'RegionalChronicDiseasePrevalence', 'RegionalAggregate',
       'GEOGRAPHIC_AREA:' || ag.GeographyID, 'county-level indicator', 'Pending'
FROM QUOTE q
JOIN ACCOUNT_GEOGRAPHY ag ON ag.AccountID = q.AccountID
WHERE q.QuoteID % 3 = 0;

INSERT INTO QUOTE_STATUS_HISTORY (QuoteID, PreviousStatus, NewStatus, ChangedBy, Reason)
SELECT QuoteID, NULL, 'Draft', 'system', 'Quote created' FROM QUOTE
UNION ALL
SELECT QuoteID, 'Draft', 'Submitted', 'agent.demo', 'Customer submitted details'
FROM QUOTE WHERE QuoteStatus <> 'Draft';

-- Convert the accepted quotes into contracts.
INSERT INTO PAYMENT_AUTHORIZATION (QuoteID, AuthorizationReference, PaymentMethodType,
                                   AuthorizedAmount, AuthorizationStatus, AuthorizedAt)
SELECT QuoteID, 'AUTH-' || LPAD(QuoteID::text, 8, '0'), 'Card',
       EstimatedPremium, 'Authorized', now()
FROM QUOTE WHERE QuoteStatus = 'Accepted';

INSERT INTO CONTRACT (ContractID, ContractNumber, AccountID, LineOfBusiness, PlanName,
                      Status, EffectiveDate)
SELECT 1000 + q.QuoteID, 'C-Q' || LPAD(q.QuoteID::text, 6, '0'), q.AccountID,
       q.ProductLine, 'Converted Plan', 'Active', q.EffectiveDate
FROM QUOTE q WHERE q.QuoteStatus = 'Accepted'
ON CONFLICT (ContractID) DO NOTHING;

INSERT INTO QUOTE_CONVERSION (QuoteID, ContractID, ConversionStatus)
SELECT q.QuoteID, 1000 + q.QuoteID, 'Completed'
FROM QUOTE q WHERE q.QuoteStatus = 'Accepted';

UPDATE QUOTE SET QuoteStatus = 'Converted'
WHERE QuoteID IN (SELECT QuoteID FROM QUOTE_CONVERSION);

INSERT INTO QUOTE_STATUS_HISTORY (QuoteID, PreviousStatus, NewStatus, ChangedBy, Reason)
SELECT QuoteID, 'Accepted', 'Converted', 'system', 'Contract issued'
FROM QUOTE_CONVERSION;

\echo 'Seed complete. Row counts:'
SELECT 'QUOTE' t, count(*) FROM QUOTE
UNION ALL SELECT 'QUOTE_COVERAGE', count(*) FROM QUOTE_COVERAGE
UNION ALL SELECT 'QUOTE_RISK_FACTOR', count(*) FROM QUOTE_RISK_FACTOR
UNION ALL SELECT 'QUOTE_STATUS_HISTORY', count(*) FROM QUOTE_STATUS_HISTORY
UNION ALL SELECT 'PAYMENT_AUTHORIZATION', count(*) FROM PAYMENT_AUTHORIZATION
UNION ALL SELECT 'QUOTE_CONVERSION', count(*) FROM QUOTE_CONVERSION
ORDER BY 1;

-- ---------------------------------------------------------------------
\echo ''
\echo 'TEST W1: invalid quote status must be rejected'
INSERT INTO QUOTE (QuoteNumber, CustomerID, ProductLine, QuoteStatus, RequestedDate)
VALUES ('Q-BAD-1', 1, 'Life', 'NotARealStatus', DATE '2026-01-01');
\echo '  ^ expected: violates ck_quote_status'

\echo ''
\echo 'TEST W2: duplicate quote number must be rejected'
INSERT INTO QUOTE (QuoteNumber, CustomerID, ProductLine, QuoteStatus, RequestedDate)
VALUES ('Q-000001', 1, 'Life', 'Draft', DATE '2026-01-01');
\echo '  ^ expected: violates uq_quote_number'

\echo ''
\echo 'TEST W3: effective date after expiration must be rejected'
INSERT INTO QUOTE (QuoteNumber, CustomerID, ProductLine, QuoteStatus, RequestedDate,
                   EffectiveDate, ExpirationDate)
VALUES ('Q-BAD-3', 1, 'Life', 'Draft', DATE '2026-01-01',
        DATE '2026-12-01', DATE '2026-06-01');
\echo '  ^ expected: violates ck_quote_dates'

\echo ''
\echo 'TEST W4: negative premium must be rejected'
INSERT INTO QUOTE (QuoteNumber, CustomerID, ProductLine, QuoteStatus, RequestedDate,
                   EstimatedPremium)
VALUES ('Q-BAD-4', 1, 'Life', 'Draft', DATE '2026-01-01', -500);
\echo '  ^ expected: violates ck_quote_premium'

\echo ''
\echo 'TEST W5: a quote cannot convert twice'
INSERT INTO QUOTE_CONVERSION (QuoteID, ContractID)
SELECT QuoteID, ContractID FROM QUOTE_CONVERSION LIMIT 1;
\echo '  ^ expected: violates uq_quote_conversion_quote'

\echo ''
\echo 'TEST W6: quote referencing a nonexistent customer must be rejected'
INSERT INTO QUOTE (QuoteNumber, CustomerID, ProductLine, QuoteStatus, RequestedDate)
VALUES ('Q-BAD-6', 999999, 'Life', 'Draft', DATE '2026-01-01');
\echo '  ^ expected: violates foreign key on CustomerID'

\echo ''
\echo 'TEST W7: unknown risk-factor source type must be rejected'
INSERT INTO QUOTE_RISK_FACTOR (QuoteID, RiskFactorType, SourceType, FactorValue)
VALUES (1, 'Test', 'PatientMedicalRecord', 'x');
\echo '  ^ expected: violates ck_qrf_source (patient-level sources are not permitted)'

\echo ''
\echo 'TEST W8: status history with no actual change must be rejected'
INSERT INTO QUOTE_STATUS_HISTORY (QuoteID, PreviousStatus, NewStatus, ChangedBy)
VALUES (1, 'Draft', 'Draft', 'tester');
\echo '  ^ expected: violates ck_qsh_change'

\echo ''
\echo 'TEST W9: unknown payment method must be rejected'
INSERT INTO PAYMENT_AUTHORIZATION (QuoteID, AuthorizationReference, PaymentMethodType,
                                   AuthorizedAmount)
VALUES (1, 'AUTH-TEST-9', 'Cryptocurrency', 100);
\echo '  ^ expected: violates ck_pa_method'

\echo ''
\echo '--- Positive check: valid transitions are accepted ---'
INSERT INTO QUOTE (QuoteNumber, CustomerID, ProductLine, QuoteStatus, RequestedDate,
                   EffectiveDate, ExpirationDate, EstimatedPremium)
VALUES ('Q-VALID-1', 5, 'A&H', 'Draft', DATE '2026-02-01',
        DATE '2026-03-01', DATE '2026-12-31', 2400.00);
SELECT 'valid quote inserted: ' || QuoteNumber FROM QUOTE WHERE QuoteNumber = 'Q-VALID-1';

\echo ''
\echo '=== Workflow constraint tests complete ==='
