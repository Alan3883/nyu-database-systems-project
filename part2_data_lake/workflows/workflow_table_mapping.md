# Workflow to Table Mapping

Maps each use case to the tables it reads and writes, and records which constraint enforces
each business rule.

## Tables added for the workflow

| Table | Rows after seeding | Purpose |
|-------|--------------------|---------|
| `QUOTE` | 121 | Quote header and status |
| `QUOTE_COVERAGE` | 180 | Proposed coverage lines |
| `QUOTE_RISK_FACTOR` | 40 | Factors reviewed while rating |
| `QUOTE_STATUS_HISTORY` | 240 | Append-only transition log |
| `PAYMENT_AUTHORIZATION` | 20 | Gateway authorization reference |
| `QUOTE_CONVERSION` | 20 | Quote-to-contract link |

Six new tables. No Part II table was renamed or dropped.

## Tables reused from Part I and Part II

| Table | Role in the workflow |
|-------|----------------------|
| `CUSTOMER` | The person or entity buying coverage (UC-01) |
| `ACCOUNT` | Employer, group, or direct account (UC-02) |
| `ACCOUNT_MEMBER` | Links a customer to an employer account |
| `ASSOCIATE`, `MANAGER_CONTRACT` | Selling associate and their agreement |
| `CONTRACT` | **The issued policy** (UC-13) |
| `CONTRACT_BENEFIT`, `CONTRACT_PREMIUM` | Policy structure and pricing (UC-14) |
| `ACCOUNT_GEOGRAPHY`, `GEOGRAPHIC_AREA` | Regional context resolution (UC-07) |
| `MV_ACCOUNT_REGIONAL_HEALTH_PROFILE` | Pre-joined regional indicators (UC-07) |
| `DATA_ASSET` | Policy document metadata (UC-16) |

## Use case to table matrix

| UC | Name | Reads | Creates | Updates |
|----|------|-------|---------|---------|
| 01 | Identify or register customer | CUSTOMER, CUSTOMER_RELATIONSHIP | CUSTOMER | CUSTOMER.UpdatedAt |
| 02 | Identify account | ACCOUNT, ACCOUNT_MEMBER, ACCOUNT_ALIAS | ACCOUNT, ACCOUNT_MEMBER | — |
| 03 | Select product line | CONTRACT, ACCOUNT_BILLING_ACCOUNT | — | — |
| 04 | Enter quote details | ASSOCIATE, MANAGER_CONTRACT | QUOTE, QUOTE_STATUS_HISTORY | — |
| 05 | Select coverage and benefits | CONTRACT_BENEFIT | QUOTE_COVERAGE | — |
| 06 | Validate required information | QUOTE, QUOTE_COVERAGE, CUSTOMER, ACCOUNT | QUOTE_STATUS_HISTORY | QUOTE.QuoteStatus |
| 07 | Retrieve regional context | ACCOUNT_GEOGRAPHY, GEOGRAPHIC_AREA, MV_ACCOUNT_REGIONAL_HEALTH_PROFILE | QUOTE_RISK_FACTOR | — |
| 08 | Review risk factors | QUOTE_RISK_FACTOR, QUOTE_COVERAGE | QUOTE_RISK_FACTOR | QUOTE_RISK_FACTOR.ReviewStatus |
| 09 | Calculate estimated quote | QUOTE_COVERAGE, QUOTE_RISK_FACTOR, CONTRACT_PREMIUM | QUOTE_STATUS_HISTORY | QUOTE.EstimatedPremium, QUOTE_COVERAGE.ProposedPremium |
| 10 | Present quote | QUOTE, QUOTE_COVERAGE, CUSTOMER, ACCOUNT | QUOTE_STATUS_HISTORY | QUOTE.QuoteStatus |
| 11 | Accept / reject / expire | QUOTE | QUOTE_STATUS_HISTORY | QUOTE.QuoteStatus |
| 12 | Record payment authorization | QUOTE | PAYMENT_AUTHORIZATION | — |
| 13 | Convert quote into CONTRACT | QUOTE, QUOTE_COVERAGE, PAYMENT_AUTHORIZATION | CONTRACT, QUOTE_CONVERSION | QUOTE.QuoteStatus |
| 14 | Create benefit and premium rows | QUOTE_COVERAGE, MANAGER_CONTRACT | CONTRACT_BENEFIT, CONTRACT_PREMIUM | — |
| 15 | Store status history | QUOTE | QUOTE_STATUS_HISTORY | — |
| 16 | Produce policy document metadata | CONTRACT, CONTRACT_BENEFIT, CONTRACT_PREMIUM, CUSTOMER | DATA_ASSET | — |

## Business rule to constraint mapping

Every rule below is enforced by the database, and each has a matching negative test in
`database/tests/workflow_constraint_tests.sql`.

| Rule | Constraint | Test |
|------|------------|------|
| Quote status must be a known value | `ck_quote_status` | W1 |
| Quote numbers are unique | `uq_quote_number` | W2 |
| Effective date cannot follow expiration | `ck_quote_dates` | W3 |
| Premiums cannot be negative | `ck_quote_premium` | W4 |
| A quote converts at most once | `uq_quote_conversion_quote` | W5 |
| Quotes reference a real customer | FK `quote_customerid_fkey` | W6 |
| **Risk factors cannot come from a patient-level source** | `ck_qrf_source` | W7 |
| Status history records an actual change | `ck_qsh_change` | W8 |
| Payment methods are a known set | `ck_pa_method` | W9 |
| Coverage amounts cannot be negative | `ck_quote_cov_amounts` | — |
| Authorization references are unique | `uq_payment_auth_ref` | — |

All nine negative tests fired correctly. Evidence: `database/evidence/database_validation.txt`.

## Privacy and fairness controls in the workflow

| Control | Mechanism |
|---------|-----------|
| No patient-level health data can enter a quote | `ck_qrf_source` allows only CustomerDeclared, InternalRecord, RegionalAggregate, ProductRule |
| Regional data stays at county level | UC-07 reads `GEOGRAPHIC_AREA` and the materialized view; neither holds an individual record |
| Provenance of every risk factor is explicit | `QUOTE_RISK_FACTOR.SourceType` and `SourceReference` |
| No cardholder data is stored | `PAYMENT_AUTHORIZATION` holds only the gateway reference |
| Policy documents are not stored in the database | UC-16 records a `DATA_ASSET` row with path and SHA-256 |
| The audit trail cannot be rewritten | `insurance_app` holds INSERT and SELECT but no UPDATE or DELETE on `QUOTE_STATUS_HISTORY` |
| Analysts cannot read tax identifiers | Column-level grant excludes `CUSTOMER.SSN_TIN` |

## Indexes serving the workflow

| Index | Query it supports |
|-------|-------------------|
| `ix_quote_open_status` | Open work queue, partial over the four open statuses |
| `ix_quote_customer_date` | A customer's quote history, newest first |
| `ix_qsh_quote_time` | A quote's transitions in order |
| `ix_conversion_contract` | Finding the quote behind a contract |
| `uq_quote_conversion_quote` | Enforces single conversion and serves quote-side lookup |

## Diagrams

| File | Notation | Content |
|------|----------|---------|
| `quote_to_policy_workflow.mmd` / `.svg` / `.png` | Mermaid flowchart (activity style) | All 16 use cases, status transitions, decision branches, audit path |
| `quote_to_policy_sequence.mmd` / `.svg` / `.png` | Mermaid sequence diagram | Actor and system interactions on the successful conversion path |
