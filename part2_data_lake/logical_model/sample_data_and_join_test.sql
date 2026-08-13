-- Small sample rows to test the schema and one structured-to-hybrid join.
-- The join path is:
--   ACCOUNT -> ACCOUNT_GEOGRAPHY -> GEOGRAPHIC_AREA -> HEALTH_OBSERVATION -> HEALTH_INDICATOR

-- Internal (structured) rows.
INSERT INTO ACCOUNT (AccountID, AccountName, CompanyCode, Address1, City, State, Zip, AccountType, Status, StartDate)
VALUES (1, 'Acme Manufacturing', 'ACME', '1 Main St', 'Little Rock', 'AR', '72201', 'Group', 'Active', DATE '2020-01-01');

INSERT INTO CUSTOMER (CustomerID, CustLastName, CustFirstName, CustomerType, Status)
VALUES (1, 'Doe', 'Jane', 'Individual', 'Active');

INSERT INTO ACCOUNT_MEMBER (AccountID, CustomerID, StartDate, EmploymentType, Status)
VALUES (1, 1, DATE '2021-03-01', 'Full-time', 'Active');

INSERT INTO CONTRACT (ContractID, ContractNumber, AccountID, LineOfBusiness, PlanName, Status, EffectiveDate)
VALUES (1, 'C-1001', 1, 'A&H', 'Standard Health', 'Active', DATE '2021-01-01');

INSERT INTO CONTRACT_BENEFIT (BenefitID, ContractID, BenefitName, BenefitType, EffectiveDate)
VALUES (1, 1, 'Medical', 'Base', DATE '2021-01-01');

INSERT INTO CONTRACT_PREMIUM (PremiumID, BenefitID, AnnualizedPremium, YearNumber, EffectiveDate)
VALUES (1, 1, 4200.00, 2021, DATE '2021-01-01');

-- Hybrid rows.
INSERT INTO DATASET (DatasetID, DatasetName, SourceOrganization, DataClassification, GeographicLevel, TimePeriod, StorageZone, Status)
VALUES ('DS001', 'CDC PLACES County 2025', 'Centers for Disease Control and Prevention', 'Structured', 'County', '2025', 'raw/cdc_places_county', 'Ingested');

INSERT INTO GEOGRAPHIC_AREA (GeographyID, ParentGeographyID, GeographyType, GeographyName, StateCode, CountyFIPS, CountryCode)
VALUES (1, NULL, 'Nation', 'United States', NULL, NULL, 'US'),
       (100, 1, 'State', 'Arkansas', 'AR', NULL, 'US'),
       (1000, 100, 'County', 'Pulaski', 'AR', '05119', 'US');

INSERT INTO HEALTH_INDICATOR (IndicatorID, IndicatorCode, IndicatorName, DiseaseCategory, FactorCategory, Unit)
VALUES (1, 'DIABETES', 'Diagnosed diabetes among adults', 'Health Outcomes', 'Disease outcome', '%');

INSERT INTO HEALTH_OBSERVATION (ObservationID, DatasetID, GeographyID, IndicatorID, ObservationYear, PopulationGroup, StratificationType, StratificationValue, MeasureValue)
VALUES (1, 'DS001', 1000, 1, 2023, 'Adults 18+', 'Overall', 'Overall', 12.5);

-- Link the internal account to the county.
INSERT INTO ACCOUNT_GEOGRAPHY (AccountID, GeographyID, RelationshipType, StartDate)
VALUES (1, 1000, 'PrimaryLocation', DATE '2020-01-01');

-- Test join: account -> geography -> observation -> indicator.
SELECT a.AccountName,
       g.GeographyName,
       g.StateCode,
       hi.IndicatorName,
       ho.ObservationYear,
       ho.MeasureValue,
       hi.Unit
FROM ACCOUNT a
JOIN ACCOUNT_GEOGRAPHY ag ON ag.AccountID = a.AccountID
JOIN GEOGRAPHIC_AREA g    ON g.GeographyID = ag.GeographyID
JOIN HEALTH_OBSERVATION ho ON ho.GeographyID = g.GeographyID
JOIN HEALTH_INDICATOR hi  ON hi.IndicatorID = ho.IndicatorID
WHERE a.AccountID = 1;
