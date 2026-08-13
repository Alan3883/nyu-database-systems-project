# Model Artifacts

| File | Contents |
|------|----------|
| `tfidf_vectorizer.joblib` | Fitted `TfidfVectorizer` (1-2 grams, min_df=2, max_df=0.8, 520 terms) |
| `kmeans_model.joblib` | Fitted `KMeans` (K=6, seed 42, n_init=25) |
| `model_metadata.json` | Version, seed, metrics, library versions, intended and prohibited uses |

## Load and apply

```python
import joblib
vec = joblib.load("ml/models/tfidf_vectorizer.joblib")
km  = joblib.load("ml/models/kmeans_model.joblib")
cluster = km.predict(vec.transform(["housing cost burden among low income renters"]))
```

## Reproducibility

Trained with seed 42. Rerunning `python3 -m ml.src.run_pipeline` reproduces byte-identical
assignments and metrics; this is asserted by `ml/tests/test_reproducibility.py`.

Recorded in `model_metadata.json`: Python version, scikit-learn version, numpy version, and
the complete configuration.

## Governance

`model_metadata.json` carries `requires_human_review: true` and an explicit
`prohibited_use` list. The database enforces the review gate: `ML_CLUSTER_SUMMARY` rejects
`HumanReviewed = TRUE` unless a reviewer and timestamp are supplied.

## Retraining triggers

- The DS010 checksum changes (source document revised)
- Additional unstructured documents are added to the corpus
- The chunking or feature configuration changes
- More than 12 months elapse since the last run
