"""Build processed and curated tables for the hybrid data model.

The script reads the raw CDC PLACES county file. It standardizes columns and
writes a processed extract. It then builds the curated tables that match the
hybrid entities in the logical schema:

  curated/geographic_area.csv        (nation, states, counties)
  curated/health_indicator.csv       (measures from PLACES and CDI)
  curated/health_observation_sample.csv (sampled county observations)
  curated/dataset.csv                 (dataset metadata rows)
  curated/data_asset.csv              (physical file rows)

Public data is aggregate and regional. No patient-level record is created.
A fixed random seed makes the sample reproducible.

Usage:
    python3 scripts/03_build_curated_data.py
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
PROCESSED = ROOT / "processed"
CURATED = ROOT / "curated"
METADATA = ROOT / "metadata"
LOG_FILE = ROOT / "logs" / "03_build_curated_data.log"

SEED = 42
SAMPLE_PER_MEASURE = 8  # counties kept per measure in the observation sample

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, mode="w"), logging.StreamHandler()],
)
log = logging.getLogger("curate")

PLACES = RAW / "cdc_places_county" / "places_county_2025.csv"
CDI = RAW / "cdc_chronic_disease_indicators" / "us_chronic_disease_indicators.csv"


def classify_factor(category: str) -> str:
    """Map a PLACES category to a simple factor group."""
    category = (category or "").lower()
    if "risk" in category or "behavior" in category:
        return "Behavioral risk factor"
    if "outcome" in category:
        return "Disease outcome"
    if "prevention" in category:
        return "Prevention measure"
    if "status" in category:
        return "Health status"
    if "disability" in category:
        return "Disability"
    return "Other"


def build_geography(places: pd.DataFrame) -> pd.DataFrame:
    """Build a nation/state/county geography table from PLACES county rows."""
    # Exclude national aggregate rows (StateAbbr 'US') and rows with no county
    # name. These are summary rows, not counties.
    counties = places[
        (places["StateAbbr"] != "US") & (places["LocationName"].notna())
    ]
    counties = (
        counties[["StateAbbr", "StateDesc", "LocationName", "LocationID"]]
        .dropna(subset=["LocationID"])
        .drop_duplicates(subset=["LocationID"])
        .sort_values("LocationID")
    )
    counties["LocationID"] = counties["LocationID"].str.zfill(5)
    counties["StateFIPS"] = counties["LocationID"].str[:2]

    rows: list[dict[str, object]] = []
    # Nation row.
    rows.append({
        "GeographyID": 1, "ParentGeographyID": "", "GeographyType": "Nation",
        "GeographyName": "United States", "StateCode": "", "CountyFIPS": "",
        "ZCTA": "", "CountryCode": "US",
    })

    # State rows.
    state_ids: dict[str, int] = {}
    states = counties[["StateAbbr", "StateDesc", "StateFIPS"]].drop_duplicates().sort_values("StateFIPS")
    next_id = 100
    for _, s in states.iterrows():
        state_ids[s["StateFIPS"]] = next_id
        rows.append({
            "GeographyID": next_id, "ParentGeographyID": 1, "GeographyType": "State",
            "GeographyName": s["StateDesc"], "StateCode": s["StateAbbr"],
            "CountyFIPS": "", "ZCTA": "", "CountryCode": "US",
        })
        next_id += 1

    # County rows.
    county_id = 1000
    for _, c in counties.iterrows():
        parent = state_ids.get(c["StateFIPS"], "")
        rows.append({
            "GeographyID": county_id, "ParentGeographyID": parent, "GeographyType": "County",
            "GeographyName": c["LocationName"], "StateCode": c["StateAbbr"],
            "CountyFIPS": c["LocationID"], "ZCTA": "", "CountryCode": "US",
        })
        county_id += 1

    geo = pd.DataFrame(rows)
    log.info("Geography rows: %d (states=%d, counties=%d)",
             len(geo), len(states), len(counties))
    return geo


def build_indicators(places: pd.DataFrame, cdi: pd.DataFrame) -> pd.DataFrame:
    """Build a health indicator table from PLACES and CDI measures."""
    rows: list[dict[str, object]] = []
    indicator_id = 1

    p = (places[["MeasureId", "Measure", "Category", "Data_Value_Unit"]]
         .drop_duplicates(subset=["MeasureId"]).dropna(subset=["MeasureId"]))
    for _, m in p.iterrows():
        rows.append({
            "IndicatorID": indicator_id,
            "IndicatorCode": m["MeasureId"],
            "IndicatorName": m["Measure"],
            "DiseaseCategory": m["Category"],
            "FactorCategory": classify_factor(m["Category"]),
            "Unit": m["Data_Value_Unit"] or "",
            "SourceDataset": "DS001",
            "Description": m["Measure"],
        })
        indicator_id += 1

    c = (cdi[["QuestionID", "Question", "Topic", "DataValueUnit"]]
         .drop_duplicates(subset=["QuestionID"]).dropna(subset=["QuestionID"]))
    for _, m in c.iterrows():
        rows.append({
            "IndicatorID": indicator_id,
            "IndicatorCode": m["QuestionID"],
            "IndicatorName": m["Question"],
            "DiseaseCategory": m["Topic"],
            "FactorCategory": "Chronic disease indicator",
            "Unit": m["DataValueUnit"] or "",
            "SourceDataset": "DS002",
            "Description": m["Question"],
        })
        indicator_id += 1

    ind = pd.DataFrame(rows)
    log.info("Indicator rows: %d (PLACES=%d, CDI=%d)", len(ind), len(p), len(c))
    return ind


def build_observations(places: pd.DataFrame, geo: pd.DataFrame,
                       ind: pd.DataFrame) -> pd.DataFrame:
    """Build a sampled county observation table joined to geography and indicator."""
    geo_key = geo[geo["GeographyType"] == "County"][["GeographyID", "CountyFIPS"]]
    geo_map = dict(zip(geo_key["CountyFIPS"], geo_key["GeographyID"]))
    ind_map = dict(zip(ind[ind["SourceDataset"] == "DS001"]["IndicatorCode"],
                       ind[ind["SourceDataset"] == "DS001"]["IndicatorID"]))

    df = places[places["StateAbbr"] != "US"].copy()
    df["LocationID"] = df["LocationID"].str.zfill(5)
    # Keep crude prevalence rows, which have one value per county and measure.
    df = df[df["DataValueTypeID"] == "CrdPrv"]
    df = df.dropna(subset=["Data_Value", "MeasureId", "LocationID"])

    # Sample a fixed number of counties per measure. This keeps every measure
    # category while limiting the file size. Sampling by index preserves all
    # columns, including the grouping column.
    sampled_index: list = []
    for _, group in df.groupby("MeasureId"):
        take = min(len(group), SAMPLE_PER_MEASURE)
        sampled_index.extend(group.sample(take, random_state=SEED).index)
    sampled = df.loc[sampled_index]

    rows: list[dict[str, object]] = []
    obs_id = 1
    skipped = 0
    for _, r in sampled.iterrows():
        gid = geo_map.get(r["LocationID"])
        iid = ind_map.get(r["MeasureId"])
        if gid is None or iid is None:
            skipped += 1
            continue
        rows.append({
            "ObservationID": obs_id,
            "DatasetID": "DS001",
            "GeographyID": gid,
            "IndicatorID": iid,
            "ObservationYear": r["Year"],
            "PopulationGroup": "Adults 18+",
            "StratificationType": "Overall",
            "StratificationValue": "Overall",
            "MeasureValue": r["Data_Value"],
            "LowerConfidenceLimit": r["Low_Confidence_Limit"] or "",
            "UpperConfidenceLimit": r["High_Confidence_Limit"] or "",
            "Notes": "Crude prevalence, county level",
        })
        obs_id += 1

    obs = pd.DataFrame(rows)
    log.info("Observation sample rows: %d (skipped unmatched=%d, source rows=%d)",
             len(obs), skipped, len(df))
    return obs


def build_dataset_and_asset() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build DATASET and DATA_ASSET curated rows from existing metadata."""
    catalog = pd.read_csv(METADATA / "dataset_catalog.csv", dtype=str)
    dataset = pd.DataFrame({
        "DatasetID": catalog["DatasetID"],
        "DatasetName": catalog["DatasetName"],
        "SourceOrganization": catalog["SourceOrganization"],
        "SourceURL": catalog["SourceURL"],
        "DataClassification": catalog["DataClassification"],
        "GeographicLevel": catalog["GeographicLevel"],
        "TimePeriod": catalog["TimePeriod"],
        "UpdateFrequency": catalog["UpdateFrequency"],
        "LicenseText": catalog["License"],
        "StorageZone": catalog["StorageZone"],
        "Status": "Ingested",
    })

    # Exact file-to-dataset mapping from the download manifest. Each raw file
    # maps to its own dataset id, not to a folder-level default.
    manifest = json.loads((METADATA / "download_manifest.json").read_text())
    # Entries without a relative_path (for example skipped downloads) are ignored.
    path_to_ds = {d["relative_path"]: d["dataset_id"]
                  for d in manifest["downloads"] if "relative_path" in d}

    inv_path = METADATA / "file_inventory.csv"
    assets = pd.DataFrame()
    if inv_path.exists():
        inv = pd.read_csv(inv_path, dtype=str)
        inv = inv[inv["Zone"] == "raw"]

        unmapped = [p for p in inv["RelativePath"] if p not in path_to_ds]
        for p in unmapped:
            log.warning("Raw file not in download manifest: %s", p)

        def asset_type(ext: str) -> str:
            return "unstructured document" if ext.lower() == "pdf" else "raw file"

        assets = pd.DataFrame({
            "AssetID": range(1, len(inv) + 1),
            "DatasetID": [path_to_ds.get(p, "") for p in inv["RelativePath"]],
            "FileName": inv["FileName"],
            "RelativePath": inv["RelativePath"],
            "CloudURI": "",
            "FileFormat": inv["Extension"].str.upper(),
            "AssetType": [asset_type(e) for e in inv["Extension"]],
            "FileSizeBytes": inv["FileSizeBytes"],
            "RowCount": inv["RowCount"],
            "ColumnCount": inv["ColumnCount"],
            "SHA256": inv["SHA256"],
            "Status": "Stored",
        })
    log.info("Dataset rows: %d, Data asset rows: %d", len(dataset), len(assets))
    return dataset, assets


def main() -> int:
    if not PLACES.exists():
        log.error("Missing PLACES file: %s", PLACES)
        return 1

    log.info("Reading PLACES county file")
    places = pd.read_csv(PLACES, dtype=str, keep_default_na=False, na_values=[""],
                         low_memory=False)
    log.info("Reading CDI file")
    cdi = pd.read_csv(CDI, dtype=str, keep_default_na=False, na_values=[""],
                      low_memory=False)

    # Processed extract: standardized column names for the PLACES county data.
    processed = places.rename(columns={
        "Year": "year", "StateAbbr": "state_abbr", "StateDesc": "state_name",
        "LocationName": "county_name", "LocationID": "county_fips",
        "Category": "category", "MeasureId": "measure_id", "Measure": "measure",
        "Data_Value": "measure_value", "Data_Value_Unit": "measure_unit",
        "Low_Confidence_Limit": "ci_low", "High_Confidence_Limit": "ci_high",
        "DataValueTypeID": "value_type_id", "TotalPopulation": "total_population",
    })
    keep = ["year", "state_abbr", "state_name", "county_name", "county_fips",
            "category", "measure_id", "measure", "measure_value", "measure_unit",
            "ci_low", "ci_high", "value_type_id", "total_population"]
    processed = processed[keep].copy()
    processed["county_fips"] = processed["county_fips"].str.zfill(5)
    processed.to_csv(PROCESSED / "cdc_places_county_clean.csv", index=False)
    log.info("Wrote processed extract: %d rows", len(processed))

    geo = build_geography(places)
    ind = build_indicators(places, cdi)
    obs = build_observations(places, geo, ind)
    dataset, assets = build_dataset_and_asset()

    geo.to_csv(CURATED / "geographic_area.csv", index=False)
    ind.to_csv(CURATED / "health_indicator.csv", index=False)
    obs.to_csv(CURATED / "health_observation_sample.csv", index=False)
    dataset.to_csv(CURATED / "dataset.csv", index=False)
    assets.to_csv(CURATED / "data_asset.csv", index=False)

    if obs.empty:
        log.error("Observation sample is empty.")
        return 1
    log.info("Curated build complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
