"""Create small sample files for the submission package.

Raw datasets are large. The submission includes a small header sample from
each raw dataset plus the curated tables. Files are written to the
sample_data/ folder. The full raw data stays in the raw zone.

Usage:
    python3 scripts/05_create_submission_samples.py
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
CURATED = ROOT / "curated"
SAMPLE_DIR = ROOT / "sample_data"
LOG_FILE = ROOT / "logs" / "05_create_submission_samples.log"

SAMPLE_ROWS = 200

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, mode="w"), logging.StreamHandler()],
)
log = logging.getLogger("samples")

RAW_SAMPLES = [
    (RAW / "cdc_places_county" / "places_county_2025.csv",
     "sample_places_county_2025.csv", 1),
    (RAW / "cdc_chronic_disease_indicators" / "us_chronic_disease_indicators.csv",
     "sample_us_chronic_disease_indicators.csv", 1),
    (RAW / "county_health_rankings" / "county_health_rankings_analytic_2025.csv",
     "sample_county_health_rankings_analytic_2025.csv", 2),
    (RAW / "census_acs_5year" / "acs5_2024_S2701_health_insurance_county.csv",
     "sample_acs5_2024_S2701_health_insurance_county.csv", 1),
]


def main() -> int:
    SAMPLE_DIR.mkdir(exist_ok=True)
    made = 0

    for src, out_name, header_rows in RAW_SAMPLES:
        if not src.exists():
            log.warning("Missing raw file: %s", src)
            continue
        # Read the header rows plus a fixed number of data rows.
        nrows = SAMPLE_ROWS
        df = pd.read_csv(src, dtype=str, header=list(range(header_rows)) if header_rows > 1 else 0,
                         nrows=nrows, keep_default_na=False, low_memory=False)
        df.to_csv(SAMPLE_DIR / out_name, index=False)
        made += 1
        log.info("Wrote %s (%d rows)", out_name, len(df))

    # Copy curated tables. The observation table is already a sample.
    for name in ["geographic_area.csv", "health_indicator.csv",
                 "health_observation_sample.csv", "dataset.csv", "data_asset.csv"]:
        src = CURATED / name
        if src.exists():
            shutil.copy2(src, SAMPLE_DIR / name)
            made += 1
            log.info("Copied curated %s", name)
        else:
            log.warning("Missing curated file: %s", name)

    # Excerpt of the unstructured PDF report (first pages only). The full
    # report stays in the raw zone.
    pdf_src = RAW / "unstructured_documents" / "chr_2025_national_report.pdf"
    if pdf_src.exists():
        try:
            from pypdf import PdfReader, PdfWriter
            reader = PdfReader(str(pdf_src))
            writer = PdfWriter()
            for page in reader.pages[:3]:
                writer.add_page(page)
            out = SAMPLE_DIR / "sample_chr_2025_report_excerpt.pdf"
            with out.open("wb") as handle:
                writer.write(handle)
            made += 1
            log.info("Wrote %s (3 of %d pages)", out.name, len(reader.pages))
        except Exception as exc:  # noqa: BLE001 - sample is optional
            log.warning("Could not create PDF excerpt: %s", exc)
    else:
        log.warning("No unstructured PDF found at %s", pdf_src)

    if made == 0:
        log.error("No sample files were created.")
        return 1
    log.info("Created %d sample files in %s", made, SAMPLE_DIR.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
