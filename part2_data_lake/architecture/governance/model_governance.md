# Model Governance

Governs the DS010 theme-discovery model. Directly addresses the requirement in Section 1 of
the assignment to "safeguard enterprises against potential bias subsumed in socio-technical
systems and limit the decision power of such systems to ensure fairness, accountability, and
transparency."

## 1. Model identity

| Field | Value |
|-------|-------|
| Name | `ds010_theme_discovery` |
| Version | 1.0.0 |
| Algorithm | TF-IDF + K-means (unsupervised) |
| Random seed | 42 |
| Training asset | DS010, 2025 County Health Rankings & Roadmaps Report |
| Corpus | 32 paragraph chunks from 18 pages |
| Selected K | 6 |
| Silhouette | 0.1212 |
| Davies-Bouldin | 2.2855 |
| Recorded in | `ML_RUN` (config and metrics as JSONB), `ml/models/model_metadata.json` |

## 2. Purpose

Identify recurring public-health and community-risk themes in one public report and organise
them into interpretable groups supporting insurance product **research** and regional
portfolio **review**.

The model is a reading aid for analysts. It is not a decision system.

## 3. Prohibited uses

The following are forbidden. They are listed in `model_metadata.json` and asserted by
`ml/tests/test_model_outputs.py::test_model_metadata_declares_prohibited_uses`.

1. Individual underwriting or eligibility decisions
2. Premium or rate setting
3. Customer-level risk scoring
4. Medical diagnosis or clinical advice
5. Any use treating a regional aggregate as personal health data

## 4. Bias risk — the specific hazard in this project

This is the central fairness concern and it is concrete, not theoretical.

**The hazard.** County-level health indicators correlate strongly with race and income. The
model's own output demonstrates this: cluster 1 (school funding) surfaced the term "black"
among its top terms, because the source report discusses racial disparity in school funding.
A model trained on county health data will therefore encode racial and economic geography.

**Why it matters here.** The hybrid model links `ACCOUNT` to `GEOGRAPHIC_AREA` and thence to
`HEALTH_OBSERVATION`. That link exists so an insurer can understand its regional portfolio.
If the same link were used to price an individual policy, the result would be a proxy for
race and income — discriminatory in effect regardless of intent, and in most U.S. insurance
markets, unlawful.

**Controls applied.**

| Control | Mechanism | Enforced by |
|---------|-----------|-------------|
| No customer-level linkage | No table joins a health observation to a `CUSTOMER` | Schema design |
| Regional data only | `HEALTH_OBSERVATION` holds county and state aggregates | Schema design |
| Source of every risk factor is explicit | `QUOTE_RISK_FACTOR.SourceType` | `ck_qrf_source` |
| Patient-level sources cannot be recorded | Only four source types permitted | `ck_qrf_source` |
| Regional context is advisory, not a rating input | Documented in UC-07 and UC-09 | Process control |
| ML output cannot reach an insurance table | `ml_writer` role has no write access to any insurance table | `06_permissions.sql` |

**Residual risk.** The process control at UC-09 — that regional context informs underwriter
awareness but is not a rating input — is a documented rule, not a database constraint. A
future implementation should enforce it in the rating engine and audit it.

## 5. Human review gate

No cluster interpretation is approved until a person reviews it.

`ML_CLUSTER_SUMMARY.HumanReviewed` defaults to `FALSE`. The constraint `ck_mlcs_review`
rejects setting it `TRUE` without both `ReviewedAt` and `ReviewedBy`. This is verified by
test M7 in `database/tests/ml_result_constraint_tests.sql`, which confirms the database
refuses an unattributed review.

**Current state: all six clusters are unreviewed.** The interpretations in
`ml/outputs/business_insights.md` are model output plus the author's reading, not approved
business findings.

## 6. Transparency

| Aspect | How it is made transparent |
|--------|----------------------------|
| What the model saw | `ds010_page_text.csv`, `ds010_chunks.csv` |
| How it grouped | `cluster_assignments.csv` with distance to centroid |
| Why each cluster exists | `top_terms_by_cluster.csv`, `representative_chunks.csv` |
| Why K=6 | `selection_reason` in `model_metrics.json`, recorded verbatim |
| Traceability to source | Every chunk carries its page number; `DOCUMENT_CHUNK` → `DATA_ASSET` → `DATASET` |
| Full configuration | `ML_RUN.ConfigurationJSON` |

Any finding can be traced from a cluster back to a page of the original PDF.

## 7. Accountability

| Role | Responsibility |
|------|----------------|
| Model author | Pipeline correctness, reproducibility, honest metric reporting |
| Reviewing analyst | Judging whether a cluster label is supported; sets `HumanReviewed` |
| Data owner | Source licence and retention |
| Underwriting leadership | Approving or rejecting any operational use |

The reviewer's name is stored in `ML_CLUSTER_SUMMARY.ReviewedBy`, so every approved
interpretation is attributable to a person.

## 8. Reproducibility

Seed 42 with the recorded configuration reproduces byte-identical outputs. Verified twice:

- `ml/tests/test_reproducibility.py` — 8 tests comparing a fresh training run against the
  exported artifacts
- Direct check: two consecutive pipeline runs produced identical SHA-256 for
  `cluster_assignments.csv`

Library versions are captured in `model_metadata.json`.

## 9. Known limitations

1. One document cannot represent the insurance market.
2. Silhouette 0.1212 indicates weak, overlapping cluster separation.
3. Cluster 2 is largely a citation-boilerplate artefact.
4. Cluster labels are generated from top terms and are provisional.
5. Results establish no causation.
6. 32 chunks is a small sample; adding documents could change the structure substantially.

## 10. Retraining triggers

- DS010 checksum changes
- Additional unstructured documents added
- Chunking or feature configuration changes
- Twelve months elapse
- A reviewer rejects the current clustering as uninterpretable

## 11. Decision-power limit

The assignment requires limiting the decision power of socio-technical systems. In this
project the limit is explicit:

**The model's maximum authority is to suggest which passages of a public report an analyst
should read.** It cannot write to an insurance table, cannot influence a premium, and cannot
be consulted about a person. Every step from model output to business action passes through
a named human reviewer.
