-- =====================================================================
-- Project Part II - Logical Relational Schema
-- Target: PostgreSQL 16
-- Author: Alan Mo (bm3883)
--
-- This schema is generated from the Part I conceptual ER model.
-- It has two parts:
--   1. Part I insurance entities (Account, Customer, Associate, Contract).
--   2. A small hybrid extension that links internal accounts to public
--      health data through geographic areas.
--
-- The schema is in third normal form. RoleType, RelationshipType,
-- ProductLine, Status, and CustomerType are kept as coded text fields to
-- keep the design simple. This is a documented simplification.
-- =====================================================================

-- Drop in dependency order so the script can run again.
DROP TABLE IF EXISTS ACCOUNT_GEOGRAPHY CASCADE;
DROP TABLE IF EXISTS HEALTH_OBSERVATION CASCADE;
DROP TABLE IF EXISTS HEALTH_INDICATOR CASCADE;
DROP TABLE IF EXISTS GEOGRAPHIC_AREA CASCADE;
DROP TABLE IF EXISTS DATA_ASSET CASCADE;
DROP TABLE IF EXISTS DATASET CASCADE;
DROP TABLE IF EXISTS CUSTOMER_ASSOCIATE_ROLE CASCADE;
DROP TABLE IF EXISTS CUSTOMER_BENEFIT_ROLE CASCADE;
DROP TABLE IF EXISTS CUSTOMER_CONTRACT_ROLE CASCADE;
DROP TABLE IF EXISTS CUSTOMER_RELATIONSHIP CASCADE;
DROP TABLE IF EXISTS CONTRACT_PREMIUM CASCADE;
DROP TABLE IF EXISTS CONTRACT_BENEFIT CASCADE;
DROP TABLE IF EXISTS CONTRACT CASCADE;
DROP TABLE IF EXISTS ASSOCIATE_RELATIONSHIP CASCADE;
DROP TABLE IF EXISTS ACCOUNT_MANAGER_CONTRACT CASCADE;
DROP TABLE IF EXISTS MANAGER_CONTRACT CASCADE;
DROP TABLE IF EXISTS ACCOUNT_MEMBER CASCADE;
DROP TABLE IF EXISTS ASSOCIATE CASCADE;
DROP TABLE IF EXISTS CUSTOMER CASCADE;
DROP TABLE IF EXISTS ACCOUNT_RELATIONSHIP CASCADE;
DROP TABLE IF EXISTS ACCOUNT_ADMIN_ASSIGNMENT CASCADE;
DROP TABLE IF EXISTS ACCOUNT_ADMIN CASCADE;
DROP TABLE IF EXISTS ACCOUNT_BILLING_ACCOUNT CASCADE;
DROP TABLE IF EXISTS BILLING_ACCOUNT CASCADE;
DROP TABLE IF EXISTS ACCOUNT_ALIAS CASCADE;
DROP TABLE IF EXISTS ACCOUNT CASCADE;

-- =====================================================================
-- SUBJECT AREA: ACCOUNT
-- =====================================================================

CREATE TABLE ACCOUNT (
    AccountID    INTEGER      PRIMARY KEY,
    AccountName  VARCHAR(200) NOT NULL,
    CompanyCode  VARCHAR(20)  NOT NULL,
    Address1     VARCHAR(200),
    City         VARCHAR(100),
    State        VARCHAR(2),
    Zip          VARCHAR(10),
    AccountType  VARCHAR(30)  NOT NULL,
    Status       VARCHAR(20)  NOT NULL,
    StartDate    DATE,
    EndDate      DATE,
    CONSTRAINT uq_account_business
        UNIQUE (AccountName, Address1, City, State, Zip, CompanyCode),
    CONSTRAINT ck_account_dates
        CHECK (EndDate IS NULL OR StartDate IS NULL OR StartDate <= EndDate)
);
COMMENT ON TABLE ACCOUNT IS
    'Consolidated employer, group, or individual/direct account. Business uniqueness includes CompanyCode.';

CREATE TABLE ACCOUNT_ALIAS (
    AliasID        INTEGER      PRIMARY KEY,
    AccountID      INTEGER      NOT NULL REFERENCES ACCOUNT (AccountID),
    SourceSystem   VARCHAR(50)  NOT NULL,
    SourceRecordID VARCHAR(50),
    AliasName      VARCHAR(200),
    AliasAddress   VARCHAR(200),
    DuplicateFlag  VARCHAR(1),
    DateReceived   DATE
);
COMMENT ON TABLE ACCOUNT_ALIAS IS
    'Original source-system records before consolidation into ACCOUNT.';

CREATE TABLE BILLING_ACCOUNT (
    BillingAccountID INTEGER      PRIMARY KEY,
    BillingName      VARCHAR(200) NOT NULL,
    BillingAddress1  VARCHAR(200),
    BillingCity      VARCHAR(100),
    BillingState     VARCHAR(2),
    BillingZip       VARCHAR(10),
    Status           VARCHAR(20)  NOT NULL
);

CREATE TABLE ACCOUNT_BILLING_ACCOUNT (
    AccountID        INTEGER     NOT NULL REFERENCES ACCOUNT (AccountID),
    BillingAccountID INTEGER     NOT NULL REFERENCES BILLING_ACCOUNT (BillingAccountID),
    ProductLine      VARCHAR(20) NOT NULL,
    EmployeeClass    VARCHAR(30),
    RelationshipType VARCHAR(30),
    StartDate        DATE,
    EndDate          DATE,
    PRIMARY KEY (AccountID, BillingAccountID, ProductLine),
    CONSTRAINT ck_acct_bill_dates
        CHECK (EndDate IS NULL OR StartDate IS NULL OR StartDate <= EndDate)
);
COMMENT ON TABLE ACCOUNT_BILLING_ACCOUNT IS
    'Resolves ACCOUNT to BILLING_ACCOUNT many-to-many. Supports separate invoices per product line.';

CREATE TABLE ACCOUNT_ADMIN (
    AdminID      INTEGER      PRIMARY KEY,
    AdminName    VARCHAR(200) NOT NULL,
    Phone        VARCHAR(30),
    EmailAddress VARCHAR(200),
    Specialty    VARCHAR(50)
);

CREATE TABLE ACCOUNT_ADMIN_ASSIGNMENT (
    AccountID   INTEGER     NOT NULL REFERENCES ACCOUNT (AccountID),
    AdminID     INTEGER     NOT NULL REFERENCES ACCOUNT_ADMIN (AdminID),
    ProductLine VARCHAR(20) NOT NULL,
    RoleType    VARCHAR(30),
    StartDate   DATE,
    EndDate     DATE,
    PRIMARY KEY (AccountID, AdminID, ProductLine),
    CONSTRAINT ck_acct_admin_dates
        CHECK (EndDate IS NULL OR StartDate IS NULL OR StartDate <= EndDate)
);

CREATE TABLE ACCOUNT_RELATIONSHIP (
    MasterAccountID  INTEGER     NOT NULL REFERENCES ACCOUNT (AccountID),
    MemberAccountID  INTEGER     NOT NULL REFERENCES ACCOUNT (AccountID),
    RelationshipType VARCHAR(30) NOT NULL,
    StartDate        DATE,
    EndDate          DATE,
    PRIMARY KEY (MasterAccountID, MemberAccountID, RelationshipType),
    CONSTRAINT ck_acct_rel_self CHECK (MasterAccountID <> MemberAccountID),
    CONSTRAINT ck_acct_rel_dates
        CHECK (EndDate IS NULL OR StartDate IS NULL OR StartDate <= EndDate)
);
COMMENT ON TABLE ACCOUNT_RELATIONSHIP IS
    'Recursive master/member links between accounts. Two roles use two foreign keys to ACCOUNT.';

-- =====================================================================
-- SUBJECT AREA: CUSTOMER
-- =====================================================================

CREATE TABLE CUSTOMER (
    CustomerID   INTEGER      PRIMARY KEY,
    CustLastName VARCHAR(100),
    CustFirstName VARCHAR(100),
    CustDOB      DATE,
    CustomerType VARCHAR(20)  NOT NULL,
    SSN_TIN      VARCHAR(20),
    Status       VARCHAR(20)  NOT NULL
);
COMMENT ON TABLE CUSTOMER IS
    'A person or legal entity. CustomerType separates Individual, Trust, and Estate.';

CREATE TABLE ACCOUNT_MEMBER (
    AccountID      INTEGER     NOT NULL REFERENCES ACCOUNT (AccountID),
    CustomerID     INTEGER     NOT NULL REFERENCES CUSTOMER (CustomerID),
    StartDate      DATE        NOT NULL,
    EmploymentType VARCHAR(30),
    Status         VARCHAR(20),
    EndDate        DATE,
    PRIMARY KEY (AccountID, CustomerID, StartDate),
    CONSTRAINT ck_acct_member_dates
        CHECK (EndDate IS NULL OR StartDate <= EndDate)
);
COMMENT ON TABLE ACCOUNT_MEMBER IS
    'Employment history between an account and a customer. StartDate is part of the key to keep multiple periods.';

-- =====================================================================
-- SUBJECT AREA: ASSOCIATE
-- =====================================================================

CREATE TABLE ASSOCIATE (
    AssociateID    INTEGER     PRIMARY KEY,
    AssocLastName  VARCHAR(100),
    AssocFirstName VARCHAR(100),
    AssocDOB       DATE,
    TenureDate     DATE,
    Status         VARCHAR(20) NOT NULL
);

CREATE TABLE MANAGER_CONTRACT (
    ManagerContractID      INTEGER     PRIMARY KEY,
    AssociateID            INTEGER     NOT NULL REFERENCES ASSOCIATE (AssociateID),
    WritingNumber          VARCHAR(30) NOT NULL,
    SitCode                VARCHAR(30) NOT NULL,
    PrimarySitCodeFlag     VARCHAR(1),
    CommissionChainCode    VARCHAR(30),
    ProductionCreditRegion VARCHAR(30),
    IssueDate              DATE,
    Status                 VARCHAR(20) NOT NULL,
    CONSTRAINT uq_manager_contract
        UNIQUE (AssociateID, WritingNumber, SitCode)
);
COMMENT ON TABLE MANAGER_CONTRACT IS
    'Selling agreement for an associate. Business uniqueness is AssociateID, WritingNumber, and SitCode.';

CREATE TABLE ACCOUNT_MANAGER_CONTRACT (
    AccountID         INTEGER     NOT NULL REFERENCES ACCOUNT (AccountID),
    ManagerContractID INTEGER     NOT NULL REFERENCES MANAGER_CONTRACT (ManagerContractID),
    RoleType          VARCHAR(30) NOT NULL,
    StartDate         DATE,
    EndDate           DATE,
    PRIMARY KEY (AccountID, ManagerContractID, RoleType),
    CONSTRAINT ck_acct_mgr_dates
        CHECK (EndDate IS NULL OR StartDate IS NULL OR StartDate <= EndDate)
);

CREATE TABLE ASSOCIATE_RELATIONSHIP (
    AssociateID        INTEGER     NOT NULL REFERENCES ASSOCIATE (AssociateID),
    RelatedAssociateID INTEGER     NOT NULL REFERENCES ASSOCIATE (AssociateID),
    RelationshipType   VARCHAR(30) NOT NULL,
    StartDate          DATE,
    EndDate            DATE,
    PRIMARY KEY (AssociateID, RelatedAssociateID, RelationshipType),
    CONSTRAINT ck_assoc_rel_self CHECK (AssociateID <> RelatedAssociateID),
    CONSTRAINT ck_assoc_rel_dates
        CHECK (EndDate IS NULL OR StartDate IS NULL OR StartDate <= EndDate)
);

-- =====================================================================
-- SUBJECT AREA: CONTRACT
-- =====================================================================

CREATE TABLE CONTRACT (
    ContractID     INTEGER      PRIMARY KEY,
    ContractNumber VARCHAR(50)  NOT NULL,
    AccountID      INTEGER      NOT NULL REFERENCES ACCOUNT (AccountID),
    LineOfBusiness VARCHAR(30),
    PlanName       VARCHAR(100),
    Status         VARCHAR(20)  NOT NULL,
    EffectiveDate  DATE,
    EndDate        DATE,
    CONSTRAINT uq_contract_number UNIQUE (ContractNumber),
    CONSTRAINT ck_contract_dates
        CHECK (EndDate IS NULL OR EffectiveDate IS NULL OR EffectiveDate <= EndDate)
);
COMMENT ON TABLE CONTRACT IS
    'Each contract links to exactly one ACCOUNT in the current simplified model.';

CREATE TABLE CONTRACT_BENEFIT (
    BenefitID     INTEGER      PRIMARY KEY,
    ContractID    INTEGER      NOT NULL REFERENCES CONTRACT (ContractID),
    BenefitName   VARCHAR(100) NOT NULL,
    BenefitType   VARCHAR(30),
    EffectiveDate DATE,
    EndDate       DATE,
    CONSTRAINT ck_benefit_dates
        CHECK (EndDate IS NULL OR EffectiveDate IS NULL OR EffectiveDate <= EndDate)
);
COMMENT ON TABLE CONTRACT_BENEFIT IS
    'A benefit or rider inside a contract. One contract contains many benefits.';

CREATE TABLE CONTRACT_PREMIUM (
    PremiumID         INTEGER        PRIMARY KEY,
    BenefitID         INTEGER        NOT NULL REFERENCES CONTRACT_BENEFIT (BenefitID),
    ManagerContractID INTEGER        REFERENCES MANAGER_CONTRACT (ManagerContractID),
    AnnualizedPremium NUMERIC(14,2),
    YearNumber        INTEGER,
    EffectiveDate     DATE,
    EndDate           DATE,
    CONSTRAINT ck_premium_dates
        CHECK (EndDate IS NULL OR EffectiveDate IS NULL OR EffectiveDate <= EndDate)
);
COMMENT ON TABLE CONTRACT_PREMIUM IS
    'Priced premium for a benefit and year. Optionally credits a manager contract.';

-- =====================================================================
-- ROLE AND RELATIONSHIP ASSOCIATIVE TABLES (CUSTOMER)
-- =====================================================================

CREATE TABLE CUSTOMER_RELATIONSHIP (
    CustomerID        INTEGER     NOT NULL REFERENCES CUSTOMER (CustomerID),
    RelatedCustomerID INTEGER     NOT NULL REFERENCES CUSTOMER (CustomerID),
    RelationshipType  VARCHAR(30) NOT NULL,
    StartDate         DATE,
    EndDate           DATE,
    PRIMARY KEY (CustomerID, RelatedCustomerID, RelationshipType),
    CONSTRAINT ck_cust_rel_self CHECK (CustomerID <> RelatedCustomerID),
    CONSTRAINT ck_cust_rel_dates
        CHECK (EndDate IS NULL OR StartDate IS NULL OR StartDate <= EndDate)
);

CREATE TABLE CUSTOMER_CONTRACT_ROLE (
    CustomerID INTEGER     NOT NULL REFERENCES CUSTOMER (CustomerID),
    ContractID INTEGER     NOT NULL REFERENCES CONTRACT (ContractID),
    RoleType   VARCHAR(30) NOT NULL,
    StartDate  DATE,
    EndDate    DATE,
    PRIMARY KEY (CustomerID, ContractID, RoleType),
    CONSTRAINT ck_cust_contract_dates
        CHECK (EndDate IS NULL OR StartDate IS NULL OR StartDate <= EndDate)
);
COMMENT ON TABLE CUSTOMER_CONTRACT_ROLE IS
    'Roles a customer plays on a contract, such as Owner, Payer, or Insured.';

CREATE TABLE CUSTOMER_BENEFIT_ROLE (
    CustomerID INTEGER     NOT NULL REFERENCES CUSTOMER (CustomerID),
    BenefitID  INTEGER     NOT NULL REFERENCES CONTRACT_BENEFIT (BenefitID),
    RoleType   VARCHAR(30) NOT NULL,
    StartDate  DATE,
    EndDate    DATE,
    PRIMARY KEY (CustomerID, BenefitID, RoleType),
    CONSTRAINT ck_cust_benefit_dates
        CHECK (EndDate IS NULL OR StartDate IS NULL OR StartDate <= EndDate)
);

CREATE TABLE CUSTOMER_ASSOCIATE_ROLE (
    CustomerID  INTEGER     NOT NULL REFERENCES CUSTOMER (CustomerID),
    AssociateID INTEGER     NOT NULL REFERENCES ASSOCIATE (AssociateID),
    RoleType    VARCHAR(30) NOT NULL,
    StartDate   DATE,
    EndDate     DATE,
    PRIMARY KEY (CustomerID, AssociateID, RoleType),
    CONSTRAINT ck_cust_assoc_dates
        CHECK (EndDate IS NULL OR StartDate IS NULL OR StartDate <= EndDate)
);

-- =====================================================================
-- HYBRID EXTENSION: DATA LAKE AND PUBLIC HEALTH DATA
-- These entities connect internal accounts to aggregate public data.
-- No patient-level health record is stored.
-- =====================================================================

CREATE TABLE DATASET (
    DatasetID          VARCHAR(10)  PRIMARY KEY,
    DatasetName        VARCHAR(200) NOT NULL,
    SourceOrganization VARCHAR(200) NOT NULL,
    SourceURL          VARCHAR(500),
    DataClassification VARCHAR(50),
    GeographicLevel    VARCHAR(50),
    TimePeriod         VARCHAR(50),
    UpdateFrequency    VARCHAR(50),
    LicenseText        VARCHAR(200),
    StorageZone        VARCHAR(100),
    IngestionDate      DATE,
    Status             VARCHAR(20)
);
COMMENT ON TABLE DATASET IS
    'Dataset-level metadata for each public data source in the data lake.';

CREATE TABLE DATA_ASSET (
    AssetID       INTEGER     PRIMARY KEY,
    DatasetID     VARCHAR(10) REFERENCES DATASET (DatasetID),
    FileName      VARCHAR(200) NOT NULL,
    RelativePath  VARCHAR(300),
    CloudURI      VARCHAR(500),
    FileFormat    VARCHAR(20),
    AssetType     VARCHAR(30),
    FileSizeBytes BIGINT,
    RowCount      INTEGER,
    ColumnCount   INTEGER,
    SHA256        CHAR(64),
    SchemaVersion VARCHAR(20),
    IngestionDate DATE,
    Status        VARCHAR(20)
);
COMMENT ON TABLE DATA_ASSET IS
    'One physical file or object per row. Can be CSV, JSON, XLSX, PDF, or another stored object.';

CREATE TABLE GEOGRAPHIC_AREA (
    GeographyID       INTEGER     PRIMARY KEY,
    ParentGeographyID INTEGER     REFERENCES GEOGRAPHIC_AREA (GeographyID),
    GeographyType     VARCHAR(20) NOT NULL,
    GeographyName     VARCHAR(150) NOT NULL,
    StateCode         VARCHAR(2),
    CountyFIPS        VARCHAR(5),
    ZCTA              VARCHAR(5),
    CountryCode       VARCHAR(2)
);
COMMENT ON TABLE GEOGRAPHIC_AREA IS
    'Common geographic key for internal and external data. Self-reference builds nation/state/county levels.';

CREATE TABLE HEALTH_INDICATOR (
    IndicatorID     INTEGER      PRIMARY KEY,
    IndicatorCode   VARCHAR(30)  NOT NULL,
    IndicatorName   VARCHAR(300) NOT NULL,
    DiseaseCategory VARCHAR(100),
    FactorCategory  VARCHAR(100),
    Unit            VARCHAR(30),
    Description     VARCHAR(500)
);
COMMENT ON TABLE HEALTH_INDICATOR IS
    'A disease, risk factor, or population measure from the public datasets.';

CREATE TABLE HEALTH_OBSERVATION (
    ObservationID        INTEGER      PRIMARY KEY,
    DatasetID            VARCHAR(10)  NOT NULL REFERENCES DATASET (DatasetID),
    GeographyID          INTEGER      NOT NULL REFERENCES GEOGRAPHIC_AREA (GeographyID),
    IndicatorID          INTEGER      NOT NULL REFERENCES HEALTH_INDICATOR (IndicatorID),
    ObservationYear      INTEGER,
    PopulationGroup      VARCHAR(50),
    StratificationType   VARCHAR(50),
    StratificationValue  VARCHAR(50),
    MeasureValue         NUMERIC(12,4),
    LowerConfidenceLimit NUMERIC(12,4),
    UpperConfidenceLimit NUMERIC(12,4),
    Notes                VARCHAR(200),
    CONSTRAINT ck_observation_year
        CHECK (ObservationYear IS NULL OR (ObservationYear BETWEEN 1990 AND 2026))
);
COMMENT ON TABLE HEALTH_OBSERVATION IS
    'Aggregate regional health values curated from raw assets. No patient-level data.';

CREATE TABLE ACCOUNT_GEOGRAPHY (
    AccountID        INTEGER     NOT NULL REFERENCES ACCOUNT (AccountID),
    GeographyID      INTEGER     NOT NULL REFERENCES GEOGRAPHIC_AREA (GeographyID),
    RelationshipType VARCHAR(30) NOT NULL,
    StartDate        DATE,
    EndDate          DATE,
    PRIMARY KEY (AccountID, GeographyID, RelationshipType),
    CONSTRAINT ck_acct_geo_dates
        CHECK (EndDate IS NULL OR StartDate IS NULL OR StartDate <= EndDate)
);
COMMENT ON TABLE ACCOUNT_GEOGRAPHY IS
    'Links an account to one or more geographic areas. Bridge between internal and public data.';

-- =====================================================================
-- INDEXES ON FOREIGN KEYS AND COMMON JOIN FIELDS
-- =====================================================================

CREATE INDEX ix_account_alias_account       ON ACCOUNT_ALIAS (AccountID);
CREATE INDEX ix_acct_bill_billing           ON ACCOUNT_BILLING_ACCOUNT (BillingAccountID);
CREATE INDEX ix_acct_admin_assign_admin     ON ACCOUNT_ADMIN_ASSIGNMENT (AdminID);
CREATE INDEX ix_acct_rel_member             ON ACCOUNT_RELATIONSHIP (MemberAccountID);
CREATE INDEX ix_account_member_customer     ON ACCOUNT_MEMBER (CustomerID);
CREATE INDEX ix_manager_contract_associate  ON MANAGER_CONTRACT (AssociateID);
CREATE INDEX ix_acct_mgr_contract           ON ACCOUNT_MANAGER_CONTRACT (ManagerContractID);
CREATE INDEX ix_assoc_rel_related           ON ASSOCIATE_RELATIONSHIP (RelatedAssociateID);
CREATE INDEX ix_contract_account            ON CONTRACT (AccountID);
CREATE INDEX ix_benefit_contract            ON CONTRACT_BENEFIT (ContractID);
CREATE INDEX ix_premium_benefit             ON CONTRACT_PREMIUM (BenefitID);
CREATE INDEX ix_premium_manager             ON CONTRACT_PREMIUM (ManagerContractID);
CREATE INDEX ix_cust_rel_related            ON CUSTOMER_RELATIONSHIP (RelatedCustomerID);
CREATE INDEX ix_cust_contract_contract      ON CUSTOMER_CONTRACT_ROLE (ContractID);
CREATE INDEX ix_cust_benefit_benefit        ON CUSTOMER_BENEFIT_ROLE (BenefitID);
CREATE INDEX ix_cust_assoc_associate        ON CUSTOMER_ASSOCIATE_ROLE (AssociateID);
CREATE INDEX ix_data_asset_dataset          ON DATA_ASSET (DatasetID);
CREATE INDEX ix_geography_parent            ON GEOGRAPHIC_AREA (ParentGeographyID);
CREATE INDEX ix_geography_countyfips        ON GEOGRAPHIC_AREA (CountyFIPS);
CREATE INDEX ix_observation_dataset         ON HEALTH_OBSERVATION (DatasetID);
CREATE INDEX ix_observation_geography       ON HEALTH_OBSERVATION (GeographyID);
CREATE INDEX ix_observation_indicator       ON HEALTH_OBSERVATION (IndicatorID);
CREATE INDEX ix_account_geography_geo       ON ACCOUNT_GEOGRAPHY (GeographyID);

-- End of schema.
