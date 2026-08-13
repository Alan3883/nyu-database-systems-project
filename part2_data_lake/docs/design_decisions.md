# Design Decisions

Each decision records the alternatives considered and the reason for the choice.

## D1. No separate POLICY table

**Decision.** An issued policy is a `CONTRACT` row. No `POLICY` table is created.

**Alternatives.** (a) Add `POLICY` alongside `CONTRACT`. (b) Store quotes as draft `CONTRACT`
rows.

**Reason.** The Part II `CONTRACT` table already carries ContractNumber, AccountID,
LineOfBusiness, PlanName, Status, EffectiveDate, and EndDate, and owns `CONTRACT_BENEFIT` and
`CONTRACT_PREMIUM`. A parallel `POLICY` would duplicate that hierarchy and split premium
history across two trees. Option (b) fails because a quote may never convert; storing quotes
as contracts would corrupt every contract count and report.

## D2. Six new workflow tables, not more

**Decision.** `QUOTE`, `QUOTE_COVERAGE`, `QUOTE_RISK_FACTOR`, `QUOTE_STATUS_HISTORY`,
`PAYMENT_AUTHORIZATION`, `QUOTE_CONVERSION`.

**Reason.** Each holds information that exists nowhere in the Part II model: pre-sale state.
`PAYMENT_AUTHORIZATION` was included because use case 12 requires recording authorization
before conversion. Nothing else was added; product catalogue, commission calculation, and
document generation all remain out of scope as they were in Part II.

## D3. Partitioning evaluated but not applied

**Decision.** Prove the design on synthetic data; do not partition live tables.

**Reason.** `HEALTH_OBSERVATION` holds 320 rows. Measurement showed partitioning is 2.3x
*slower* than a composite index for point lookups, while giving 10x less I/O on full-period
scans. Neither benefit applies at 320 rows. Applying it now would add planning overhead and
create empty partitions. The growth design is documented and proven so it can be adopted when
volume justifies it.

## D4. Unsupervised model, not supervised

**Decision.** TF-IDF and K-means over DS010.

**Alternatives.** (a) Supervised regression predicting county chronic-disease prevalence from
socio-economic features. (b) County-level clustering of the structured data.

**Reason.** The assignment's Section 3 asks for "analytics on the unstructured data collected
in the second part". DS010 is the unstructured data and carries no labels. Option (a) would
require inventing labels, and it would produce exactly the artefact the fairness analysis
warns against: a model predicting health outcomes from demographic and economic geography,
usable as a pricing proxy for race and income. Choosing the unsupervised path over unstructured
data satisfies the assignment and avoids building the hazard.

## D5. Sub-page chunking

**Decision.** Paragraph-aware chunks of about 110 words, not whole pages.

**Reason.** Measured first: DS010 has 18 pages and 4,093 extractable words. Page-level
chunking gives 18 analysis units, too few for stable clustering. Sub-page chunking produced 32
units while preserving the source page on every chunk for traceability.

## D6. Minimum cluster size constraint on K selection

**Decision.** Disqualify any K whose smallest cluster holds fewer than four chunks, then take
the best silhouette among the rest.

**Reason.** Silhouette rises monotonically with K on a 32-chunk corpus, because splitting few
points into many groups always looks tighter. The unconstrained maximum selected K=8, which
produced two-chunk clusters. A theme supported by two passages is not a theme. The size floor
is what makes the selection defensible; K=5, 7, and 8 were excluded and K=6 was chosen.

## D7. Synthetic data for scale testing, clearly labelled

**Decision.** Generate 500,000 rows in `perf_health_observation_synthetic`, outside the data
lake.

**Reason.** The index design cannot be validated at 320 rows. Synthetic data at production
scale shows the real effect: 0.032 ms with the index versus 7.121 ms without. The `perf_`
prefix, `_synthetic` suffix, `IsSynthetic` column, and table comment all mark it as generated.
It is never written to the lake, never exported to curated, and never uploaded to cloud storage.

## D8. JSONB for model configuration and metrics

**Decision.** Store `ML_RUN.ConfigurationJSON` and `MetricsJSON` as JSONB.

**Reason.** A model run must be reproducible from the database alone, but the set of
hyperparameters changes whenever the algorithm changes. Fixed columns would need a migration
for every experiment. JSONB keeps runs comparable while allowing the configuration shape to
evolve, and PostgreSQL can still index and query inside it.

## D9. Human review enforced by constraint, not convention

**Decision.** `ck_mlcs_review` rejects `HumanReviewed = TRUE` without both `ReviewedAt` and
`ReviewedBy`.

**Reason.** A governance rule that lives only in documentation is not a control. Putting it in
the database means an approved interpretation is always attributable to a named person, and no
application bug or manual update can produce an unattributed approval. Test M7 confirms the
database refuses it.

## D10. ml_writer cannot write to any insurance table

**Decision.** The ML role gets read access to `DATASET`, `DATA_ASSET`, and the hybrid tables,
write access to the four ML tables, and nothing else.

**Reason.** This is a structural boundary rather than a procedural one. Even a compromised or
buggy ML pipeline cannot modify a customer, quote, or contract record. It makes the claim
"model output never touches a customer record" enforceable rather than aspirational.

## D11. Loaded BigQuery external tables over a native load

**Decision.** Define BigQuery tables as EXTERNAL over GCS CSV files.

**Reason.** The curated files are small and static between releases. External tables avoid a
duplicate copy and keep GCS as the single source of truth, so re-uploading a curated file
updates the analytics layer with no reload step. For a large, frequently queried warehouse a
native load would be faster; that trade-off is noted in the future-state architecture.

## D12. Cloud execution left to the project owner

**Decision.** Write and syntax-check the deployment script; do not execute it.

**Reason.** The Part II GCP project was deleted after submission to stop charges, verified by
a 404 response. Running Part III requires creating billable resources in the owner's account.
The requirement is therefore reported as not complete rather than as complete-by-script, and
`validate_part3.py` fails the build if the report claims otherwise.

## D13. Additive DDL files rather than editing the Part II schema

**Decision.** Add `database/physical/*.sql`; leave `logical_model/logical_schema.sql`
untouched.

**Reason.** The Part II logical schema is a submitted deliverable. Editing it would make the
Part II submission irreproducible. Keeping the physical layer in separate files means the Part
II artifact still loads exactly as graded, and `rollback.sql` can restore that state exactly.
