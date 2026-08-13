"""Part III machine learning pipeline for DS010 unstructured document analysis.

The pipeline discovers the DS010 PDF through the data lake metadata, extracts
and chunks its text, builds TF-IDF features, selects a cluster count, trains a
K-means model, and exports interpretable outputs.

Run with:
    python3 -m ml.src.run_pipeline
"""

__version__ = "1.0.0"
