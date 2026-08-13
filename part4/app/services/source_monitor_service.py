"""Unstructured-source change detection and versioned raw-asset capture.

Detection is by SHA-256 content hash, not modification time. A file's
mtime changes when it is copied, restored from backup, or touched, and it
does not change when a file is rewritten with identical bytes. Neither
signal is what "the source changed" means, so neither is used.

The unit of comparison is DATA_ASSET.SHA256 for the current DS010 asset
row. That column is what the pipeline recorded the last time it ingested
the source, so comparing against it makes the check idempotent: run the
monitor twice on unchanged input and the second run sees the checksum it
just wrote.

When the source has changed, the new bytes are copied into a versioned
path under raw/unstructured_documents/versions/ before anything else
happens. The previous raw file is never overwritten and never deleted;
every model run can be traced to the exact bytes it saw.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..config import CONFIG
from ..models import DataAsset, Dataset
from .errors import NotFound, ValidationError

log = logging.getLogger("part4.monitor")

DS010 = "DS010"
UNSTRUCTURED = "unstructured document"


def sha256_of(path: Path) -> str:
    """Stream a file and return its SHA-256 hex digest.

    Streamed in 1 MiB blocks: the DS010 report is 14 MB today, but a
    monitor that loads whole files into memory stops working the first
    time somebody points it at a large one.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass
class SourceState:
    """What the monitor found on this pass."""

    checked_at: datetime
    source_path: Path
    source_exists: bool
    current_sha256: str | None
    recorded_sha256: str | None
    asset_id: int | None
    asset_version: str | None
    changed: bool
    message: str

    @property
    def short_current(self) -> str:
        return (self.current_sha256 or "")[:16]

    @property
    def short_recorded(self) -> str:
        return (self.recorded_sha256 or "")[:16]


def resolve_active_asset(session: Session) -> DataAsset:
    """Find the DS010 asset row the pipeline currently treats as current.

    Resolution goes through DATASET -> DATA_ASSET, the same lineage the
    Part III pipeline uses, rather than a hard-coded path.
    """
    dataset = session.get(Dataset, DS010)
    if dataset is None:
        raise NotFound(
            "Dataset DS010 is not registered. Load the curated catalogue first.")
    asset = session.scalars(
        select(DataAsset)
        .where(DataAsset.dataset_id == DS010)
        .where(DataAsset.asset_type == UNSTRUCTURED)
        .where(DataAsset.status == "Stored")
        .order_by(desc(DataAsset.asset_id))
        .limit(1)
    ).one_or_none()
    if asset is None:
        raise NotFound("No stored DS010 unstructured asset row in DATA_ASSET.")
    return asset


def check_source(session: Session, source_path: Path | None = None) -> SourceState:
    """Compare the watched file's checksum with the recorded one.

    Read-only. This function never writes, so it is safe to call from a
    web request, a poll loop, or a test.
    """
    path = Path(source_path) if source_path else CONFIG.watch_path
    now = datetime.now(timezone.utc)
    asset = resolve_active_asset(session)

    if not path.exists():
        return SourceState(
            checked_at=now, source_path=path, source_exists=False,
            current_sha256=None, recorded_sha256=asset.sha256,
            asset_id=asset.asset_id, asset_version=asset.schema_version,
            changed=False,
            message=f"Source file not found at {path}. No action taken.")

    current = sha256_of(path)
    recorded = (asset.sha256 or "").strip().lower()
    changed = current != recorded

    if changed:
        message = (f"Source changed. Recorded {recorded[:16]}..., "
                   f"found {current[:16]}.... Retraining required.")
    else:
        message = (f"No change. Checksum {current[:16]}... matches asset "
                   f"version {asset.schema_version or 'v1'}. No retraining.")
    log.info(message)

    return SourceState(
        checked_at=now, source_path=path, source_exists=True,
        current_sha256=current, recorded_sha256=recorded,
        asset_id=asset.asset_id, asset_version=asset.schema_version,
        changed=changed, message=message)


def _next_version_label(session: Session) -> str:
    count = len(list(session.scalars(
        select(DataAsset)
        .where(DataAsset.dataset_id == DS010)
        .where(DataAsset.asset_type == UNSTRUCTURED))))
    return f"v{count + 1}"


def preserve_new_version(session: Session, source_path: Path,
                         checksum: str) -> DataAsset:
    """Copy the changed source to a versioned path and register the asset.

    Order matters. The file is copied first and the row is written second,
    so a crash between the two leaves an unreferenced file in the lake
    rather than a catalogue entry pointing at bytes that do not exist.

    The previous asset row is marked Superseded, not deleted, and its file
    stays where it is.
    """
    version = _next_version_label(session)
    CONFIG.version_path.mkdir(parents=True, exist_ok=True)
    target = CONFIG.version_path / f"{source_path.stem}_{version}_{checksum[:12]}{source_path.suffix}"

    if not target.exists():
        shutil.copy2(source_path, target)
        log.info("Preserved raw source as %s", target.relative_to(CONFIG.lake))
    else:
        log.info("Version file already present: %s", target.name)

    stored_checksum = sha256_of(target)
    if stored_checksum != checksum:
        raise ValidationError(
            "Copied source does not match the checksum that was read. "
            "The version was not registered.")

    previous = session.scalars(
        select(DataAsset)
        .where(DataAsset.dataset_id == DS010)
        .where(DataAsset.asset_type == UNSTRUCTURED)
        .where(DataAsset.status == "Stored")
    ).all()
    for row in previous:
        row.status = "Superseded"

    asset = DataAsset(
        dataset_id=DS010,
        file_name=target.name,
        relative_path=str(target.relative_to(CONFIG.lake)),
        file_format=source_path.suffix.lstrip(".").upper() or "PDF",
        asset_type=UNSTRUCTURED,
        file_size_bytes=target.stat().st_size,
        sha256=stored_checksum,
        schema_version=version,
        ingestion_date=date.today(),
        status="Stored",
    )
    session.add(asset)
    session.flush()
    log.info("Registered DATA_ASSET %d as %s", asset.asset_id, version)
    return asset
