# Business Insights from the DS010 Theme Model

Source: 2025 County Health Rankings & Roadmaps Report (dataset DS010, 18 pages).
Model: TF-IDF + K-means, K=6, random seed 42.
Corpus: 32 paragraph-level chunks, 520-term vocabulary.
Quality: silhouette 0.1212, Davies-Bouldin 2.2855.

**Status of every interpretation below: unreviewed model output.** `HumanReviewed` is
`FALSE` for all six clusters in `ML_CLUSTER_SUMMARY`. Nothing here is an approved business
finding.

---

## How to read the silhouette score

A silhouette of 0.1212 is **weak**. On a 32-chunk corpus drawn from a single document this is
expected: the chunks all come from one argument by one author, so they genuinely overlap in
vocabulary. The score says the clusters are soft groupings of a continuous discussion, not
crisply separated topics.

The practical consequence: these clusters are a **reading aid for a human analyst**, not a
classifier. They indicate which passages discuss similar material. They do not support any
automated decision.

---

## Cluster 1 — Societal rules and community conditions

| Field | Value |
|-------|-------|
| Cluster ID | 5 |
| Chunks | 9 (the largest cluster) |
| Pages | 2, 5, 6, 7, 9, 16 |
| Top terms | rules, conditions, people, power, community conditions, societal rules, societal, community, laws, change |

**Interpretation.** The report's central framing: that written and unwritten societal rules
shape community conditions, which in turn shape health outcomes. Representative passages
define social determinants of health and name transportation, safe housing, living-wage jobs,
and well-resourced schools as community conditions.

**Potential insurance use.** Vocabulary alignment. When the insurer builds regional context
features, this cluster identifies the terminology and factor groupings the public-health
source itself uses, which helps map external indicators onto the internal
`HEALTH_INDICATOR.FactorCategory` field consistently.

**Required human review.** An analyst must confirm the mapping between these concepts and the
indicator categories already loaded in the hybrid model.

**Limitation.** This is one organisation's framing of causation. The model detects that the
framing is present and dominant; it provides no evidence that the framing is correct.

---

## Cluster 2 — Housing cost burden and income

| Field | Value |
|-------|-------|
| Cluster ID | 3 |
| Chunks | 4 |
| Pages | 8, 12, 17 |
| Top terms | income, renters, low income, low, housing, income renters, american, american community, survey, community survey |

**Interpretation.** Severe housing cost burden among renters, measured as housing costs above
50% of household income, and its concentration among low-income renters. The passages cite
the American Community Survey as the data source.

**Potential insurance use.** This is the most directly actionable cluster. It names a specific,
county-level, publicly available measure sourced from ACS — and the data lake already holds
four ACS county tables (DS006–DS009), including S1701 poverty and S1901 income. The cluster
identifies a concrete candidate indicator for the regional context layer.

**Required human review.** An analyst must confirm the specific ACS table and variable, and
confirm that adding it to `HEALTH_OBSERVATION` respects the aggregate-only rule.

**Limitation.** The report describes a national pattern. Applying it to a specific book of
business requires county-level joins the model has not performed.

---

## Cluster 3 — Publisher attribution and collective-action framing

| Field | Value |
|-------|-------|
| Cluster ID | 2 |
| Chunks | 7 |
| Pages | 2, 5, 7, 15, 18 |
| Top terms | health institute, wisconsin population, university, institute, wisconsin, university wisconsin, population, population health, thrive, chr |

**Interpretation.** This cluster is **partly an artefact**. Its top terms are dominated by the
publisher's name — "University of Wisconsin Population Health Institute" — which appears in
citations, credits, and the colophon. Repeated attribution text pulled these chunks together
regardless of their subject matter.

**Potential insurance use.** None directly. Its value is diagnostic: it shows that
citation boilerplate survived cleaning and formed its own group.

**Required human review.** Confirm the artefact reading, then decide whether to add publisher
names to the stop-word list before any future run.

**Limitation.** Because the grouping is driven by boilerplate, the substantive content of
these seven chunks is heterogeneous and should not be summarised as a single theme.

---

## Cluster 4 — Public health roots and community organizing

| Field | Value |
|-------|-------|
| Cluster ID | 4 |
| Chunks | 4 |
| Pages | 3, 14, 16 |
| Top terms | public health, public, organizing, community organizing, reform, goals, political, building, building power, economic |

**Interpretation.** The report's argument that public health originates in community
organizing, and its call to action for social, political, and economic reform.

**Potential insurance use.** Limited and indirect. Useful for understanding the stance of a
data source the insurer relies on, which matters when assessing whether a source's framing
introduces perspective into the measures it publishes.

**Required human review.** An analyst should note this as source-context information rather
than a business input.

**Limitation.** Advocacy content. It carries no measurable indicator.

---

## Cluster 5 — School funding and educational disparity

| Field | Value |
|-------|-------|
| Cluster ID | 1 |
| Chunks | 4 |
| Pages | 10, 11, 17 |
| Top terms | funding, school, counties, region, scores, schools, black, education, average, belt region |

**Interpretation.** Public school funding deficits, quantified in the source as more than
$3,000 additional per student annually in half of all U.S. counties, with regional
concentration.

**Potential insurance use.** Education and funding measures are candidate regional context
indicators. County Health Rankings (DS003/DS004), already in the data lake, publishes
education measures at county level.

**Required human review.** Critical here. The cluster's top terms include a racial term
("black") because the source discusses racial disparity in school funding. **This is exactly
the correlation that makes county-level indicators unsafe for pricing.** Any analyst reviewing
this cluster must treat it as a fairness warning, not a modelling opportunity. See
`architecture/governance/model_governance.md`.

**Limitation.** Education funding has no established causal link to insurance loss experience.
Treating it as a rating factor would be both unsupported and discriminatory in effect.

---

## Cluster 6 — Narratives, worldviews, and structural determinants

| Field | Value |
|-------|-------|
| Cluster ID | 0 |
| Chunks | 4 |
| Pages | 13, 14, 16 |
| Top terms | narratives, based, world, ways, worldviews, values, patterns, structural determinants, structural, practices |

**Interpretation.** The report's definitional material on narratives, worldviews, culture and
norms as "unwritten rules", including a discussion of the gender pay gap as an institutional
pattern.

**Potential insurance use.** None operationally. It is conceptual framework material.

**Required human review.** Classify as background.

**Limitation.** Qualitative and definitional. No measurable quantity.

---

## Evaluating Big Data ideas: short, medium, long term

The assignment asks for an approach to evaluating Big Data ideas by benefit horizon. Each idea
below is assessed on four criteria: data availability today, effort, fairness risk, and
whether it can be validated.

### Short term (achievable now with data already in the lake)

| Idea | Basis | Fairness risk | Status |
|------|-------|---------------|--------|
| Research support: use clusters to navigate source documents by theme | Cluster 1, 2 | Low — no customer data involved | **Implemented** |
| Data acquisition prioritisation: cluster 2 points to ACS housing-cost measures already held | Cluster 2 | Low | Ready to act on |
| Regional portfolio review: count accounts by county and view regional indicators alongside | `MV_ACCOUNT_REGIONAL_HEALTH_PROFILE` | Medium — must stay descriptive | **Implemented** |
| Vocabulary alignment between public sources and `HEALTH_INDICATOR.FactorCategory` | Cluster 1 | Low | Ready to act on |

### Medium term (needs more data or governance work)

| Idea | Prerequisite | Fairness risk | Status |
|------|--------------|---------------|--------|
| Product research: identify regions where a benefit design may address documented conditions | Multi-year observations; product data | Medium-high | Not started |
| Regional trend dashboards | Time series beyond the current single-year sample | Medium | Not started |
| Underwriting *guideline* review (not individual decisions) | Legal and actuarial review; bias audit | **High** | Not started |
| Expand the corpus to many state and CDC reports | Document acquisition | Low | Not started |

### Long term (require capabilities and approvals not yet in place)

| Idea | Prerequisite | Fairness risk | Status |
|------|--------------|---------------|--------|
| Approved forecasting models | Longitudinal data, actuarial validation, regulatory filing | **High** | **Not implemented. Not attempted in Part III.** |
| Portfolio scenario analysis | Validated forecasting | High | Not implemented |
| Rate-review support | Regulatory approval, demonstrated non-discrimination | **Very high** | Not implemented |

**Nothing in the medium or long term columns has been built.** They are candidate ideas
recorded for planning. Part III implemented only the short-term items marked *Implemented*.

---

## What this model does not establish

- It does not forecast chronic disease.
- It does not predict claims, losses, or premiums.
- It does not score any customer.
- It does not establish causation between any community condition and any health outcome.
- It does not validate the source report's claims; it only detects what the report discusses.
- It cannot generalise beyond this one document.

## How insights feed back into the EDA

The path from this model into the Part I Enterprise Data Architecture is deliberately narrow:

1. A cluster identifies a candidate **indicator concept** (for example, housing cost burden).
2. An analyst reviews it and sets `HumanReviewed = TRUE` with their name in
   `ML_CLUSTER_SUMMARY`.
3. If approved, a matching **aggregate, county-level** measure is sourced from an existing
   dataset and loaded into `HEALTH_INDICATOR` and `HEALTH_OBSERVATION`.
4. It becomes visible to the business through `GEOGRAPHIC_AREA` and
   `MV_ACCOUNT_REGIONAL_HEALTH_PROFILE`, joined to `ACCOUNT` via `ACCOUNT_GEOGRAPHY`.
5. It reaches a quote only as a `QUOTE_RISK_FACTOR` row with
   `SourceType = 'RegionalAggregate'`, which by database constraint can reference only a
   geographic area — never a person.

At no point does model output touch a `CUSTOMER` row.
