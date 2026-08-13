"""Validate the curated outputs.

The script checks that curated files exist and are not empty, that primary
keys are unique, that foreign keys resolve, and that geographic codes and
years use the expected format. Results are written to
metadata/validation_results.csv. The script exits with a nonzero status if a
serious check fails.

Usage:
    python3 scripts/04_validate_outputs.py
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CURATED = ROOT / "curated"
METADATA = ROOT / "metadata"
LOG_FILE = ROOT / "logs" / "04_validate_outputs.log"
RESULT_FILE = METADATA / "validation_results.csv"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, mode="w"), logging.StreamHandler()],
)
log = logging.getLogger("validate")

results: list[dict[str, object]] = []


def record(check: str, status: str, detail: str) -> None:
    results.append({"Check": check, "Status": status, "Detail": detail})
    level = log.info if status == "PASS" else log.error
    level("%s: %s (%s)", check, status, detail)


def main() -> int:
    serious_failures = 0
    files = {
        "geographic_area": CURATED / "geographic_area.csv",
        "health_indicator": CURATED / "health_indicator.csv",
        "health_observation_sample": CURATED / "health_observation_sample.csv",
        "dataset": CURATED / "dataset.csv",
        "data_asset": CURATED / "data_asset.csv",
    }

    frames: dict[str, pd.DataFrame] = {}
    for name, path in files.items():
        if not path.exists():
            record(f"exists:{name}", "FAIL", f"missing {path.name}")
            serious_failures += 1
            continue
        df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])
        frames[name] = df
        if df.empty:
            record(f"nonempty:{name}", "FAIL", "file has no rows")
            serious_failures += 1
        else:
            record(f"nonempty:{name}", "PASS", f"{len(df)} rows")

    # Primary key uniqueness.
    pk_map = {
        "geographic_area": "GeographyID",
        "health_indicator": "IndicatorID",
        "health_observation_sample": "ObservationID",
        "dataset": "DatasetID",
        "data_asset": "AssetID",
    }
    for name, pk in pk_map.items():
        if name not in frames:
            continue
        df = frames[name]
        dups = int(df[pk].duplicated().sum())
        if dups == 0:
            record(f"pk_unique:{name}.{pk}", "PASS", "no duplicate keys")
        else:
            record(f"pk_unique:{name}.{pk}", "FAIL", f"{dups} duplicate keys")
            serious_failures += 1

    # Foreign key resolution for observations.
    if "health_observation_sample" in frames:
        obs = frames["health_observation_sample"]
        geo_ids = set(frames["geographic_area"]["GeographyID"]) if "geographic_area" in frames else set()
        ind_ids = set(frames["health_indicator"]["IndicatorID"]) if "health_indicator" in frames else set()
        bad_geo = int((~obs["GeographyID"].isin(geo_ids)).sum())
        bad_ind = int((~obs["IndicatorID"].isin(ind_ids)).sum())
        record("fk:observation.GeographyID", "PASS" if bad_geo == 0 else "FAIL",
               f"{bad_geo} unresolved")
        record("fk:observation.IndicatorID", "PASS" if bad_ind == 0 else "FAIL",
               f"{bad_ind} unresolved")
        serious_failures += (bad_geo > 0) + (bad_ind > 0)

    # Geographic code format: county FIPS must be 5 digits.
    if "geographic_area" in frames:
        geo = frames["geographic_area"]
        counties = geo[geo["GeographyType"] == "County"]
        bad_fips = int((~counties["CountyFIPS"].str.fullmatch(r"\d{5}")).sum())
        record("format:CountyFIPS", "PASS" if bad_fips == 0 else "FAIL",
               f"{bad_fips} county rows not 5-digit")
        serious_failures += bad_fips > 0

    # Year format on observations.
    if "health_observation_sample" in frames:
        years = pd.to_numeric(frames["health_observation_sample"]["ObservationYear"], errors="coerce")
        bad_year = int(((years < 1990) | (years > 2026)).sum() + years.isna().sum())
        record("format:ObservationYear", "PASS" if bad_year == 0 else "FAIL",
               f"{bad_year} invalid years")
        serious_failures += bad_year > 0

    pd.DataFrame(results).to_csv(RESULT_FILE, index=False)
    log.info("Wrote %s with %d checks. Serious failures: %d",
             RESULT_FILE.name, len(results), serious_failures)
    return 1 if serious_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
