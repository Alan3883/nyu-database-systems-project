"""Profile the raw datasets.

For each raw dataset the script reports row count, column count, missing
values, duplicate rows, and simple geographic/year checks. It writes:

  - metadata/data_dictionary.csv    (actual source columns)
  - metadata/data_quality_report.csv (one row per dataset)

Wide files (many columns) only list key and sample columns in the data
dictionary. A note records this so the reader knows the list is capped.

Usage:
    python3 scripts/02_profile_data.py
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
LOG_FILE = ROOT / "logs" / "02_profile_data.log"
DICT_FILE = ROOT / "metadata" / "data_dictionary.csv"
DQ_FILE = ROOT / "metadata" / "data_quality_report.csv"

# For wide files we only document these key columns in the data dictionary.
MAX_FULL_COLUMNS = 40

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, mode="w"), logging.StreamHandler()],
)
log = logging.getLogger("profile")

# Datasets to profile. header_rows handles the CHR analytic file, which has a
# second header row of machine codes before the data starts.
DATASETS = [
    {
        "dataset_id": "DS001",
        "name": "CDC PLACES County 2025",
        "path": RAW / "cdc_places_county" / "places_county_2025.csv",
        "header_rows": 1,
        "geo_col": "LocationID",
        "year_col": "Year",
        "key_cols": ["Year", "StateAbbr", "LocationName", "LocationID",
                     "Category", "MeasureId", "Measure", "Data_Value"],
    },
    {
        "dataset_id": "DS002",
        "name": "US Chronic Disease Indicators",
        "path": RAW / "cdc_chronic_disease_indicators" / "us_chronic_disease_indicators.csv",
        "header_rows": 1,
        "geo_col": "LocationID",
        "year_col": "YearStart",
        "key_cols": ["YearStart", "YearEnd", "LocationAbbr", "LocationID",
                     "Topic", "Question", "DataValue", "StratificationCategory1",
                     "Stratification1"],
    },
    {
        "dataset_id": "DS004",
        "name": "County Health Rankings Analytic 2025",
        "path": RAW / "county_health_rankings" / "county_health_rankings_analytic_2025.csv",
        "header_rows": 2,
        "geo_col": "fipscode",
        "year_col": "year",
        "key_cols": ["statecode", "countycode", "fipscode", "state", "county", "year"],
    },
    {
        "dataset_id": "DS009",
        "name": "ACS 5-Year S2701 Health Insurance County",
        "path": RAW / "census_acs_5year" / "acs5_2024_S2701_health_insurance_county.csv",
        "header_rows": 1,
        "geo_col": "GEO_ID",
        "year_col": None,
        "key_cols": ["NAME", "GEO_ID", "state", "county", "S2701_C01_001E"],
    },
]


def load_csv(path: Path, header_rows: int) -> pd.DataFrame:
    """Load a CSV as strings. Skip extra header rows when present."""
    skiprows = list(range(1, header_rows)) if header_rows > 1 else None
    return pd.read_csv(
        path, dtype=str, keep_default_na=False, na_values=[""],
        skiprows=skiprows, low_memory=False,
    )


def main() -> int:
    dict_rows: list[dict[str, object]] = []
    dq_rows: list[dict[str, object]] = []

    for spec in DATASETS:
        path = Path(spec["path"])
        if not path.exists():
            log.warning("Missing dataset file: %s", path)
            continue
        log.info("Profiling %s", spec["name"])
        df = load_csv(path, int(spec["header_rows"]))
        n_rows, n_cols = df.shape

        # Data dictionary rows. Cap wide files to the key columns.
        if n_cols <= MAX_FULL_COLUMNS:
            columns = list(df.columns)
            capped = "no"
        else:
            columns = [c for c in spec["key_cols"] if c in df.columns]
            capped = "yes"
        for col in columns:
            non_null = int(df[col].notna().sum())
            dict_rows.append({
                "DatasetID": spec["dataset_id"],
                "DatasetName": spec["name"],
                "ColumnName": col,
                "NonNullCount": non_null,
                "NullCount": n_rows - non_null,
                "SampleValue": next((str(v) for v in df[col].dropna().head(1)), ""),
                "ColumnsCapped": capped,
            })

        # Data quality checks.
        dup_rows = int(df.duplicated().sum())
        key_missing = int(df[spec["geo_col"]].isna().sum()) if spec["geo_col"] in df.columns else -1

        bad_year = ""
        if spec["year_col"] and spec["year_col"] in df.columns:
            years = pd.to_numeric(df[spec["year_col"]], errors="coerce")
            bad_year = int(((years < 1990) | (years > 2026)).sum() + years.isna().sum())

        total_cells = n_rows * n_cols
        missing_cells = int(df.isna().sum().sum())
        dq_rows.append({
            "DatasetID": spec["dataset_id"],
            "DatasetName": spec["name"],
            "RowCount": n_rows,
            "ColumnCount": n_cols,
            "DuplicateRows": dup_rows,
            "MissingCells": missing_cells,
            "MissingPercent": round(100 * missing_cells / total_cells, 2) if total_cells else 0,
            "GeoKeyColumn": spec["geo_col"],
            "GeoKeyMissing": key_missing,
            "YearColumn": spec["year_col"] or "",
            "InvalidYearRows": bad_year,
            "EmptyFile": "yes" if n_rows == 0 else "no",
        })
        log.info("  rows=%d cols=%d duplicates=%d missing%%=%.2f",
                 n_rows, n_cols, dup_rows, 100 * missing_cells / total_cells if total_cells else 0)

    if not dq_rows:
        log.error("No datasets profiled.")
        return 1

    pd.DataFrame(dict_rows).to_csv(DICT_FILE, index=False)
    pd.DataFrame(dq_rows).to_csv(DQ_FILE, index=False)
    log.info("Wrote %s (%d rows) and %s (%d rows).",
             DICT_FILE.name, len(dict_rows), DQ_FILE.name, len(dq_rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
