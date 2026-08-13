"""Locate the DS010 unstructured document through data lake metadata.

The pipeline does not hard-code the PDF path. It resolves the file the same
way an application would: look up the dataset in the catalogue, find its
physical asset, then verify the checksum recorded at download time.

This keeps the ML pipeline consistent with the DATASET -> DATA_ASSET lineage
defined in the Part II hybrid model.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("discover")


@dataclass
class DocumentAsset:
    """A resolved unstructured document with its lineage metadata."""

    dataset_id: str
    dataset_name: str
    source_organization: str
    asset_id: int
    file_name: str
    relative_path: Path
    file_format: str
    asset_type: str
    expected_sha256: str
    file_size_bytes: int
    checksum_verified: bool


def sha256_of(path: Path) -> str:
    """Stream a file and return its SHA-256 hex digest."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def discover(root: Path, config: dict) -> DocumentAsset:
    """Resolve the configured dataset id to a physical document asset.

    Resolution order:
      1. curated/data_asset.csv joined to metadata/dataset_catalog.csv
      2. metadata/download_manifest.json for the recorded checksum
      3. the configured fallback path

    Raises FileNotFoundError if no readable asset can be resolved.
    """
    cfg = config["input"]
    dataset_id = cfg["dataset_id"]
    wanted_type = cfg["asset_type"]

    # --- Step 1: dataset catalogue -----------------------------------
    catalog_path = root / cfg["metadata_catalog"]
    dataset_name = ""
    source_org = ""
    if catalog_path.exists():
        with catalog_path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row.get("DatasetID") == dataset_id:
                    dataset_name = row.get("DatasetName", "")
                    source_org = row.get("SourceOrganization", "")
                    log.info("Catalogue hit: %s = %s", dataset_id, dataset_name)
                    break
    else:
        log.warning("Dataset catalogue not found at %s", catalog_path)

    # --- Step 2: data asset ------------------------------------------
    asset_path = root / cfg["data_asset_csv"]
    asset_row: dict[str, str] | None = None
    if asset_path.exists():
        with asset_path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row.get("DatasetID") == dataset_id and row.get("AssetType") == wanted_type:
                    asset_row = row
                    break
        if asset_row:
            log.info("Data asset hit: AssetID=%s file=%s",
                     asset_row.get("AssetID"), asset_row.get("FileName"))
        else:
            log.warning("No DATA_ASSET row for %s with AssetType=%r", dataset_id, wanted_type)
    else:
        log.warning("Data asset table not found at %s", asset_path)

    # --- Step 3: resolve the physical path ----------------------------
    if asset_row and asset_row.get("RelativePath"):
        pdf_path = root / asset_row["RelativePath"]
    else:
        pdf_path = root / cfg["fallback_pdf_path"]
        log.warning("Falling back to configured path: %s", pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"DS010 document not found at {pdf_path}")

    # --- Step 4: checksum --------------------------------------------
    expected = (asset_row or {}).get("SHA256", "")
    if not expected:
        manifest_path = root / cfg["download_manifest"]
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            for entry in manifest.get("downloads", []):
                if entry.get("dataset_id") == dataset_id:
                    expected = entry.get("sha256", "")
                    break

    verified = False
    if cfg.get("verify_checksum", True) and expected:
        actual = sha256_of(pdf_path)
        verified = actual == expected
        if verified:
            log.info("Checksum verified: %s", actual[:16] + "...")
        else:
            # Not fatal: the pipeline records the mismatch so the data
            # quality report can flag it, rather than silently proceeding
            # as if the file were the expected one.
            log.error("CHECKSUM MISMATCH expected=%s actual=%s", expected[:16], actual[:16])
    elif not expected:
        log.warning("No expected checksum on record; cannot verify integrity")

    return DocumentAsset(
        dataset_id=dataset_id,
        dataset_name=dataset_name or "unknown",
        source_organization=source_org or "unknown",
        asset_id=int((asset_row or {}).get("AssetID", 0) or 0),
        file_name=pdf_path.name,
        relative_path=pdf_path.relative_to(root),
        file_format=(asset_row or {}).get("FileFormat", "PDF"),
        asset_type=wanted_type,
        expected_sha256=expected,
        file_size_bytes=pdf_path.stat().st_size,
        checksum_verified=verified,
    )
