# Part III Machine Learning Pipeline

Unsupervised theme discovery over the DS010 unstructured document.

## Purpose

Identify recurring public-health and community-risk themes in the 2025 County Health
Rankings & Roadmaps report and organise them into interpretable groups that support
insurance product research and regional portfolio review.

## Why unsupervised

DS010 carries no labels, and the corpus is a single 18-page document. Supervised disease
prediction would require inventing labels and would produce a model that cannot be
validated. The assignment's Section 3 asks for analytics on the *unstructured* data, which
theme discovery satisfies directly.

## Prohibited uses

This model must not be used for individual underwriting, eligibility, premium or rate
setting, customer-level risk scoring, or medical diagnosis. See
`../architecture/governance/model_governance.md`.

## Run

```bash
python3 -m pip install -r ../scripts/requirements.txt
python3 -m ml.src.run_pipeline
```

Runs in about 3 seconds. Deterministic: seed 42 reproduces byte-identical outputs.

## Pipeline steps

| Step | Module | Function |
|------|--------|----------|
| 1 | `discover_ds010.py` | Resolve DS010 via DATASET -> DATA_ASSET; verify SHA-256 |
| 2 | `extract_pdf.py` | Extract text per page; strip running headers |
| 3 | `build_chunks.py` | Paragraph-aware chunking; preserve page numbers |
| 4 | `preprocess_text.py` | Normalize; protect domain terms |
| 5 | `train_cluster_model.py` | TF-IDF features; score candidate K; train K-means |
| 6 | `evaluate_model.py` | Top terms, representative chunks per cluster |
| 7 | `export_results.py` | CSV, JSON, PNG outputs; save model artifacts |
| - | `run_pipeline.py` | Orchestration; nonzero exit on failure |

## Why sub-page chunking

DS010 has 18 pages and ~4,224 extractable words. Page-level chunks would give 18 analysis
units, too few to cluster stably. Paragraph-aware chunking targeting ~110 words yields 32
units while preserving the source page on every chunk for traceability.

## Why K=6

Silhouette rises monotonically with K on a small corpus, so an unconstrained maximum always
over-fragments: at K=8 this corpus produces two-chunk "themes". The pipeline therefore
disqualifies any K whose smallest cluster falls below `clustering.min_cluster_size` (4), then
takes the best silhouette among the rest. K=5, 7, and 8 were excluded for fragmentation;
K=6 was selected.

## Results

| Metric | Value |
|--------|-------|
| Pages / extracted / failed | 18 / 18 / 0 |
| Chunks | 32 |
| Vocabulary | 520 terms |
| Selected K | 6 |
| Silhouette | 0.1212 (weak — see limitations) |
| Davies-Bouldin | 2.2855 |
| Cluster sizes | 4, 4, 7, 4, 4, 9 |

## Outputs

`outputs/` holds the document inventory, page text, chunks, cluster assignments, cluster
summary, top terms, representative chunks, metrics JSON, two PNG visualizations, and
`business_insights.md`.

`models/` holds the fitted vectorizer, the K-means model, and `model_metadata.json` with the
intended-use and prohibited-use declarations.

## Limitations

- One national report cannot represent the insurance market.
- A silhouette of 0.1212 means soft, overlapping groupings, not crisp topics.
- Cluster 2 is largely a citation-boilerplate artefact.
- Cluster labels are provisional until a human sets `HumanReviewed = TRUE`.
- Results establish no causation and are not customer-level predictions.

## Tests

```bash
python3 -m pytest ml/tests -v
```

44 tests covering extraction, chunking, output completeness, governance metadata, and
reproducibility.
