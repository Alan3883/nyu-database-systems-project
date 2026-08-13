"""Build a file inventory for the data lake.

The script walks the raw, processed, and curated zones. For each file it
records the path, size, checksum, and (for CSV files) row and column counts.
The output is metadata/file_inventory.csv.

Usage:
    python3 scripts/01_inventory_data.py
"""

from __future__ import annotations

import csv
import hashlib
import logging
from pathlib import Path
from typing import Optional

# Paths are relative to the data lake root (the parent of this scripts folder).
ROOT = Path(__file__).resolve().parent.parent
ZONES = ["raw", "processed", "curated", "metadata", "schema"]
OUT_FILE = ROOT / "metadata" / "file_inventory.csv"
LOG_FILE = ROOT / "logs" / "01_inventory_data.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, mode="w"), logging.StreamHandler()],
)
log = logging.getLogger("inventory")


def sha256_of(path: Path) -> str:
    """Return the SHA-256 checksum of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def csv_shape(path: Path) -> tuple[Optional[int], Optional[int]]:
    """Return (data_row_count, column_count) for a CSV file.

    Rows are counted by streaming so large files do not load into memory.
    The header row is not counted as a data row.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
            if header is None:
                return 0, 0
            col_count = len(header)
            row_count = sum(1 for _ in reader)
        return row_count, col_count
    except Exception as exc:  # noqa: BLE001 - log and continue
        log.warning("Could not read shape for %s: %s", path, exc)
        return None, None


def main() -> int:
    rows: list[dict[str, object]] = []
    for zone in ZONES:
        zone_dir = ROOT / zone
        if not zone_dir.exists():
            continue
        for path in sorted(zone_dir.rglob("*")):
            if not path.is_file():
                continue
            ext = path.suffix.lower().lstrip(".")
            row_count, col_count = (None, None)
            if ext == "csv":
                row_count, col_count = csv_shape(path)
            rows.append(
                {
                    "Zone": zone,
                    "RelativePath": path.relative_to(ROOT).as_posix(),
                    "FileName": path.name,
                    "Extension": ext,
                    "FileSizeBytes": path.stat().st_size,
                    "RowCount": "" if row_count is None else row_count,
                    "ColumnCount": "" if col_count is None else col_count,
                    "SHA256": sha256_of(path),
                }
            )
            log.info("Inventoried %s (%s bytes)", path.name, path.stat().st_size)

    if not rows:
        log.error("No files found in any zone.")
        return 1

    fieldnames = list(rows[0].keys())
    with OUT_FILE.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    log.info("Wrote %s with %d files.", OUT_FILE.name, len(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
