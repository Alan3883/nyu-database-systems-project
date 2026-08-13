# Quote-to-Policy Business Use Cases

Supports the Part III requirement for a workflow-based application that enables a customer to
obtain an insurance quote and then a policy.

**Scope note.** No database program is implemented, as the assignment permits. This document
specifies the use cases and the data each one touches. The supporting tables exist and are
constraint-tested in `database/tests/workflow_constraint_tests.sql`.

**Central design decision.** An issued policy is a `CONTRACT` row. The Part II `CONTRACT`
table already carries ContractNumber, AccountID, LineOfBusiness, PlanName, Status,
EffectiveDate, and EndDate, and it owns CONTRACT_BENEFIT and CONTRACT_PREMIUM. No separate
POLICY table is added; that would duplicate the contract hierarchy and split premium history.

## Actors

| Actor | Description |
|-------|-------------|
| Customer | Person or legal entity seeking coverage. A `CUSTOMER` row. |
| Associate | Licensed sales associate. An `ASSOCIATE` row, holding a `MANAGER_CONTRACT`. |
| Underwriter | Reviews risk factors and approves rating. |
| Quote Service | Application component that creates and rates quotes. |
| Rating Engine | Calculates estimated premium. |
| Payment Gateway | External service returning an authorization reference. |
| Regional Data Service | Read-only access to aggregate regional context. |

## Quote status model

`Draft → Submitted → Rated → Presented → Accepted → Converted`, with `Rejected` and `Expired`
as terminal states. Enforced by `ck_quote_status`; every transition is written to
`QUOTE_STATUS_HISTORY`.

---

## UC-01 Identify or register customer

| Field | Value |
|-------|-------|
| Primary actor | Customer |
| Supporting actor | Associate, Quote Service |
| Trigger | A customer requests a quote |
| Preconditions | None |
| Main flow | 1. Capture name and date of birth. 2. Search `CUSTOMER`. 3. If found, select the record. 4. If not, create a `CUSTOMER` row with CustomerType and Status='Active'. |
| Alternate flow | Multiple matches: the associate confirms identity using `CUSTOMER_RELATIONSHIP` context before selecting. |
| Exception flow | Required identity fields missing: the quote cannot leave Draft. |
| Data read | `CUSTOMER`, `CUSTOMER_RELATIONSHIP` |
| Data created | `CUSTOMER` (only when new) |
| Data updated | `CUSTOMER.UpdatedAt` via trigger |
| Postconditions | A single CustomerID is bound to the session |
| Security controls | SSN_TIN is write-only for the app role; `insurance_analyst` has no column privilege on it |
| Audit controls | `CreatedAt` / `UpdatedAt` on `CUSTOMER` |

---

## UC-02 Identify account

| Field | Value |
|-------|-------|
| Primary actor | Associate |
| Supporting actor | Quote Service |
| Trigger | UC-01 complete |
| Preconditions | A CustomerID exists |
| Main flow | 1. For group business, look up the employer in `ACCOUNT` by business key. 2. For individual business, use an Individual or Direct account. 3. Bind AccountID to the quote. |
| Alternate flow | Employer not found: create an `ACCOUNT` row honouring `uq_account_business`. |
| Exception flow | Duplicate account attempted: rejected by `uq_account_business`; the associate reuses the existing account. |
| Data read | `ACCOUNT`, `ACCOUNT_MEMBER`, `ACCOUNT_ALIAS` |
| Data created | `ACCOUNT`, `ACCOUNT_MEMBER` (only when new) |
| Data updated | None |
| Postconditions | AccountID bound to the quote |
| Security controls | Account creation restricted to the app role |
| Audit controls | `ACCOUNT.CreatedAt` / `UpdatedAt` |

---

## UC-03 Select product line

| Field | Value |
|-------|-------|
| Primary actor | Customer |
| Supporting actor | Associate |
| Trigger | Account identified |
| Preconditions | CustomerID and AccountID bound |
| Main flow | 1. Present available product lines. 2. Customer selects one (FSA, Life, or A&H). 3. Store in `QUOTE.ProductLine`. |
| Alternate flow | Multiple product lines wanted: one quote per line. |
| Exception flow | Product not offered in the account's state: the quote is blocked before rating. |
| Data read | `CONTRACT` (existing coverage), `ACCOUNT_BILLING_ACCOUNT` (ProductLine) |
| Data created | None |
| Data updated | None |
| Postconditions | ProductLine determined |
| Security controls | None beyond authentication |
| Audit controls | Recorded on the quote at creation |

---

## UC-04 Enter quote details

| Field | Value |
|-------|-------|
| Primary actor | Associate |
| Supporting actor | Quote Service |
| Trigger | Product line selected |
| Preconditions | UC-01 to UC-03 complete |
| Main flow | 1. Create a `QUOTE` row with status 'Draft'. 2. Assign a unique QuoteNumber. 3. Record RequestedDate, EffectiveDate, ExpirationDate. 4. Bind AssociateID. 5. Write the initial `QUOTE_STATUS_HISTORY` row. |
| Alternate flow | Saved and resumed later: the quote stays in Draft. |
| Exception flow | EffectiveDate after ExpirationDate: rejected by `ck_quote_dates`. |
| Data read | `ASSOCIATE`, `MANAGER_CONTRACT` |
| Data created | `QUOTE`, `QUOTE_STATUS_HISTORY` |
| Data updated | None |
| Postconditions | A Draft quote exists with a unique number |
| Security controls | Only the app role may insert into `QUOTE` |
| Audit controls | `uq_quote_number`; history row written |

---

## UC-05 Select coverage and benefits

| Field | Value |
|-------|-------|
| Primary actor | Customer |
| Supporting actor | Associate |
| Trigger | Quote created |
| Preconditions | Quote in Draft |
| Main flow | 1. Present coverage options for the product line. 2. Customer chooses coverages, limits, deductibles. 3. Insert one `QUOTE_COVERAGE` row per coverage. |
| Alternate flow | Riders added alongside the base coverage. |
| Exception flow | Negative limit or deductible: rejected by `ck_quote_cov_amounts`. |
| Data read | `CONTRACT_BENEFIT` (catalogue) |
| Data created | `QUOTE_COVERAGE` |
| Data updated | None |
| Postconditions | At least one coverage line exists |
| Security controls | App role only |
| Audit controls | `QUOTE_COVERAGE.CreatedAt` |

---

## UC-06 Validate required information

| Field | Value |
|-------|-------|
| Primary actor | Quote Service |
| Supporting actor | None |
| Trigger | Associate submits the quote |
| Preconditions | Quote in Draft with at least one coverage |
| Main flow | 1. Check customer, account, product line, dates, and coverages are present. 2. Move status to 'Submitted'. 3. Write status history. |
| Alternate flow | Warnings raised but not blocking: submission proceeds. |
| Exception flow | Mandatory data missing: the quote stays in Draft with a reason recorded. |
| Data read | `QUOTE`, `QUOTE_COVERAGE`, `CUSTOMER`, `ACCOUNT` |
| Data created | `QUOTE_STATUS_HISTORY` |
| Data updated | `QUOTE.QuoteStatus`, `QUOTE.UpdatedAt` |
| Postconditions | Quote is Submitted |
| Security controls | Status values constrained by `ck_quote_status` |
| Audit controls | Transition recorded with actor and reason |

---

## UC-07 Retrieve regional aggregate context

| Field | Value |
|-------|-------|
| Primary actor | Regional Data Service |
| Supporting actor | Underwriter |
| Trigger | Quote submitted |
| Preconditions | The account is linked to a geographic area via `ACCOUNT_GEOGRAPHY` |
| Main flow | 1. Resolve the account's county through `ACCOUNT_GEOGRAPHY`. 2. Read `MV_ACCOUNT_REGIONAL_HEALTH_PROFILE` for that area. 3. Write `QUOTE_RISK_FACTOR` rows with SourceType='RegionalAggregate' and SourceReference pointing at the GEOGRAPHIC_AREA. |
| Alternate flow | No geographic link: the step is skipped and the quote proceeds without regional context. |
| Exception flow | An attempt to record a patient-level source is rejected by `ck_qrf_source`. |
| Data read | `ACCOUNT_GEOGRAPHY`, `GEOGRAPHIC_AREA`, `MV_ACCOUNT_REGIONAL_HEALTH_PROFILE` |
| Data created | `QUOTE_RISK_FACTOR` |
| Data updated | None |
| Postconditions | Regional context is attached and clearly labelled as aggregate |
| Security controls | **The data read is county-level only. No individual health record exists in the model and none can be referenced: `ck_qrf_source` permits only CustomerDeclared, InternalRecord, RegionalAggregate, or ProductRule.** |
| Audit controls | SourceType and SourceReference make the provenance of every factor explicit |

**Fairness constraint.** Regional context is recorded for underwriter awareness and portfolio
review. It must not be used as a rating input. County-level health indicators correlate with
race and income, so using them to price an individual would be discriminatory in effect. See
`architecture/governance/model_governance.md`.

---

## UC-08 Review risk factors

| Field | Value |
|-------|-------|
| Primary actor | Underwriter |
| Supporting actor | Quote Service |
| Trigger | Risk factors recorded |
| Preconditions | Quote is Submitted |
| Main flow | 1. List `QUOTE_RISK_FACTOR` rows grouped by SourceType. 2. Underwriter reviews each. 3. Set ReviewStatus to 'Reviewed' or 'Waived'. |
| Alternate flow | Additional customer-declared factors added during review. |
| Exception flow | Factors left Pending: rating cannot complete. |
| Data read | `QUOTE_RISK_FACTOR`, `QUOTE_COVERAGE` |
| Data created | `QUOTE_RISK_FACTOR` (additional) |
| Data updated | `QUOTE_RISK_FACTOR.ReviewStatus` |
| Postconditions | All factors reviewed |
| Security controls | Underwriter role required |
| Audit controls | ReviewStatus retained per factor |

---

## UC-09 Calculate estimated quote

| Field | Value |
|-------|-------|
| Primary actor | Rating Engine |
| Supporting actor | Underwriter |
| Trigger | Risk factors reviewed |
| Preconditions | Quote is Submitted |
| Main flow | 1. Compute a proposed premium per coverage. 2. Write `QUOTE_COVERAGE.ProposedPremium`. 3. Sum into `QUOTE.EstimatedPremium`. 4. Move status to 'Rated'. |
| Alternate flow | Manual underwriter adjustment, recorded in status history with a reason. |
| Exception flow | Negative premium: rejected by `ck_quote_premium`. |
| Data read | `QUOTE_COVERAGE`, `QUOTE_RISK_FACTOR`, `CONTRACT_PREMIUM` (historic) |
| Data created | `QUOTE_STATUS_HISTORY` |
| Data updated | `QUOTE.EstimatedPremium`, `QUOTE.QuoteStatus`, `QUOTE_COVERAGE.ProposedPremium` |
| Postconditions | Quote is Rated with a premium |
| Security controls | Rating logic is out of database scope |
| Audit controls | Premium and transition recorded |

---

## UC-10 Present quote

| Field | Value |
|-------|-------|
| Primary actor | Associate |
| Supporting actor | Customer |
| Trigger | Quote rated |
| Preconditions | Quote is Rated |
| Main flow | 1. Produce the quote document. 2. Deliver to the customer. 3. Move status to 'Presented'. |
| Alternate flow | Customer requests changes: quote returns to Draft as a new version. |
| Exception flow | Delivery fails: quote stays Rated. |
| Data read | `QUOTE`, `QUOTE_COVERAGE`, `CUSTOMER`, `ACCOUNT` |
| Data created | `QUOTE_STATUS_HISTORY` |
| Data updated | `QUOTE.QuoteStatus` |
| Postconditions | Quote is Presented |
| Security controls | Document contains no SSN_TIN |
| Audit controls | Presentation timestamped |

---

## UC-11 Accept, reject, or expire quote

| Field | Value |
|-------|-------|
| Primary actor | Customer |
| Supporting actor | Quote Service |
| Trigger | Customer decision, or ExpirationDate passes |
| Preconditions | Quote is Presented |
| Main flow | 1. Customer accepts: status becomes 'Accepted'. 2. Write status history. |
| Alternate flow | Customer declines: status becomes 'Rejected' with a reason. |
| Exception flow | ExpirationDate passes with no decision: a batch job sets 'Expired'. |
| Data read | `QUOTE` |
| Data created | `QUOTE_STATUS_HISTORY` |
| Data updated | `QUOTE.QuoteStatus` |
| Postconditions | Quote is Accepted, Rejected, or Expired |
| Security controls | Only the bound customer or associate may accept |
| Audit controls | Decision, actor, and reason recorded |

---

## UC-12 Record payment authorization

| Field | Value |
|-------|-------|
| Primary actor | Payment Gateway |
| Supporting actor | Customer |
| Trigger | Quote accepted |
| Preconditions | Quote is Accepted |
| Main flow | 1. Customer supplies payment details **to the gateway**. 2. Gateway returns an authorization reference. 3. Insert `PAYMENT_AUTHORIZATION` with the reference, method type, and amount. |
| Alternate flow | Invoice or payroll deduction instead of card. |
| Exception flow | Declined: status 'Declined'; conversion cannot proceed. |
| Data read | `QUOTE` |
| Data created | `PAYMENT_AUTHORIZATION` |
| Data updated | None |
| Postconditions | An authorization reference exists |
| Security controls | **No card number, bank account, or cardholder data is stored. Only the gateway's reference. This keeps the database outside PCI scope.** Unknown methods rejected by `ck_pa_method`. |
| Audit controls | `uq_payment_auth_ref`; AuthorizedAt recorded |

---

## UC-13 Convert accepted quote into CONTRACT

| Field | Value |
|-------|-------|
| Primary actor | Quote Service |
| Supporting actor | Underwriter |
| Trigger | Payment authorized |
| Preconditions | Quote Accepted; authorization status 'Authorized' |
| Main flow | 1. Create a `CONTRACT` row with a new ContractNumber, the quote's AccountID, ProductLine as LineOfBusiness, Status 'Active'. 2. Insert `QUOTE_CONVERSION` linking quote to contract. 3. Set quote status to 'Converted'. |
| Alternate flow | Underwriter issues with amended terms, recorded in history. |
| Exception flow | A second conversion attempt is rejected by `uq_quote_conversion_quote`. |
| Data read | `QUOTE`, `QUOTE_COVERAGE`, `PAYMENT_AUTHORIZATION` |
| Data created | `CONTRACT`, `QUOTE_CONVERSION` |
| Data updated | `QUOTE.QuoteStatus` |
| Postconditions | An issued policy exists as a CONTRACT row |
| Security controls | App role holds INSERT but not DELETE on `QUOTE_CONVERSION` |
| Audit controls | **`uq_quote_conversion_quote` guarantees one quote cannot produce two policies.** |

---

## UC-14 Create benefit and premium rows

| Field | Value |
|-------|-------|
| Primary actor | Quote Service |
| Supporting actor | None |
| Trigger | Contract created |
| Preconditions | A CONTRACT row exists |
| Main flow | 1. For each `QUOTE_COVERAGE`, insert a `CONTRACT_BENEFIT`. 2. For each benefit, insert a `CONTRACT_PREMIUM` with the annualized premium and year. 3. Credit the associate's `MANAGER_CONTRACT` where applicable. |
| Alternate flow | Multi-year quotes create one premium row per year. |
| Exception flow | Effective after end date: rejected by `ck_benefit_dates` / `ck_premium_dates`. |
| Data read | `QUOTE_COVERAGE`, `MANAGER_CONTRACT` |
| Data created | `CONTRACT_BENEFIT`, `CONTRACT_PREMIUM` |
| Data updated | None |
| Postconditions | The contract hierarchy is complete |
| Security controls | App role only |
| Audit controls | Premium linked to the crediting manager contract |

---

## UC-15 Store status history

| Field | Value |
|-------|-------|
| Primary actor | Quote Service |
| Supporting actor | None |
| Trigger | Any quote status change |
| Preconditions | A quote exists |
| Main flow | 1. On every transition insert a `QUOTE_STATUS_HISTORY` row with previous status, new status, actor, and reason. |
| Alternate flow | System-generated transitions record 'system' as the actor. |
| Exception flow | A no-op transition is rejected by `ck_qsh_change`. |
| Data read | `QUOTE` |
| Data created | `QUOTE_STATUS_HISTORY` |
| Data updated | None |
| Postconditions | A complete, append-only audit trail exists |
| Security controls | **INSERT and SELECT only. No UPDATE or DELETE granted, which is what makes the trail trustworthy.** |
| Audit controls | Supports cycle-time and conversion-rate reporting |

---

## UC-16 Produce policy document metadata

| Field | Value |
|-------|-------|
| Primary actor | Quote Service |
| Supporting actor | Customer |
| Trigger | Contract issued with benefits and premiums |
| Preconditions | UC-13 and UC-14 complete |
| Main flow | 1. Generate the policy document. 2. Store it in the document store. 3. Record a `DATA_ASSET` row with file name, path, format, size, and SHA-256. |
| Alternate flow | Reissue creates a new asset row; the prior version is retained. |
| Exception flow | Generation fails: the contract remains valid and the document is retried. |
| Data read | `CONTRACT`, `CONTRACT_BENEFIT`, `CONTRACT_PREMIUM`, `CUSTOMER` |
| Data created | `DATA_ASSET` |
| Data updated | None |
| Postconditions | The document is catalogued with lineage |
| Security controls | **The document binary is not stored in PostgreSQL — only metadata, checksum, and path. This mirrors the DS010 pattern.** |
| Audit controls | SHA-256 detects later alteration |

---

## Coverage summary

| Requirement | Use cases |
|-------------|-----------|
| Obtain an insurance quote | UC-01 to UC-11 |
| Obtain a policy | UC-12 to UC-16 |
| Audit trail | UC-15, plus history rows in UC-04, 06, 09, 10, 11, 13 |
| Regional data used safely | UC-07, constrained by `ck_qrf_source` |
| No patient-level data | Enforced database-wide; no table can hold an individual health record |
