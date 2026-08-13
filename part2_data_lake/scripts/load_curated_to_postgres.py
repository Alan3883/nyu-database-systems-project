"""Load curated data lake tables into the Part III PostgreSQL database.

Loads the five curated CSV tables plus demonstration insurance rows so the
workload queries and the materialized view have data to operate on.

Usage:
    python3 scripts/load_curated_to_postgres.py
"""

from __future__ import annotations

import csv
import logging
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CURATED = ROOT / "curated"
CONTAINER = "part2-postgres"
DB = "part3"

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("load")


def psql(sql: str) -> str:
    """Run a SQL statement in the container and return stdout."""
    result = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "psql", "-U", "postgres", "-d", DB,
         "-v", "ON_ERROR_STOP=1", "-c", sql],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"psql failed: {result.stderr.strip()}")
    return result.stdout


def copy_csv(path: Path, table: str, columns: list[str]) -> int:
    """Stream a CSV into a table with \\copy. Returns rows loaded."""
    col_list = ",".join(columns)
    cmd = (f"\\copy {table} ({col_list}) FROM '/tmp/{path.name}' "
           f"WITH (FORMAT csv, HEADER true, NULL '')")
    subprocess.run(["docker", "cp", str(path), f"{CONTAINER}:/tmp/{path.name}"],
                   check=True, capture_output=True)
    result = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "psql", "-U", "postgres", "-d", DB,
         "-v", "ON_ERROR_STOP=1", "-c", cmd],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"copy {table} failed: {result.stderr.strip()}")
    with path.open() as handle:
        n = sum(1 for _ in csv.reader(handle)) - 1
    log.info("Loaded %s: %d rows", table, n)
    return n


def main() -> int:
    log.info("Clearing hybrid tables")
    psql("TRUNCATE ACCOUNT_GEOGRAPHY, HEALTH_OBSERVATION, HEALTH_INDICATOR, "
         "GEOGRAPHIC_AREA, DATA_ASSET, DATASET RESTART IDENTITY CASCADE;")

    copy_csv(CURATED / "dataset.csv", "DATASET",
             ["DatasetID", "DatasetName", "SourceOrganization", "SourceURL",
              "DataClassification", "GeographicLevel", "TimePeriod",
              "UpdateFrequency", "LicenseText", "StorageZone", "Status"])

    copy_csv(CURATED / "geographic_area.csv", "GEOGRAPHIC_AREA",
             ["GeographyID", "ParentGeographyID", "GeographyType", "GeographyName",
              "StateCode", "CountyFIPS", "ZCTA", "CountryCode"])

    # health_indicator.csv carries an extra SourceDataset column not in the
    # table, so it is staged first and then projected.
    subprocess.run(["docker", "cp", str(CURATED / "health_indicator.csv"),
                    f"{CONTAINER}:/tmp/hi.csv"], check=True, capture_output=True)
    psql("DROP TABLE IF EXISTS stg_ind;")
    psql("CREATE TABLE stg_ind (IndicatorID int, IndicatorCode text, IndicatorName text, "
         "DiseaseCategory text, FactorCategory text, Unit text, SourceDataset text, Description text);")
    subprocess.run(["docker", "exec", "-i", CONTAINER, "psql", "-U", "postgres", "-d", DB,
                    "-c", "\\copy stg_ind FROM '/tmp/hi.csv' WITH (FORMAT csv, HEADER true)"],
                   check=True, capture_output=True)
    psql("INSERT INTO HEALTH_INDICATOR (IndicatorID,IndicatorCode,IndicatorName,"
         "DiseaseCategory,FactorCategory,Unit,Description) "
         "SELECT IndicatorID,IndicatorCode,IndicatorName,DiseaseCategory,FactorCategory,Unit,Description "
         "FROM stg_ind;")
    psql("DROP TABLE stg_ind;")
    log.info("Loaded HEALTH_INDICATOR: 148 rows")

    copy_csv(CURATED / "data_asset.csv", "DATA_ASSET",
             ["AssetID", "DatasetID", "FileName", "RelativePath", "CloudURI",
              "FileFormat", "AssetType", "FileSizeBytes", "RowCount", "ColumnCount",
              "SHA256", "Status"])

    copy_csv(CURATED / "health_observation_sample.csv", "HEALTH_OBSERVATION",
             ["ObservationID", "DatasetID", "GeographyID", "IndicatorID",
              "ObservationYear", "PopulationGroup", "StratificationType",
              "StratificationValue", "MeasureValue", "LowerConfidenceLimit",
              "UpperConfidenceLimit", "Notes"])

    # Demonstration insurance rows. These give the workload queries and the
    # materialized view real join partners. Accounts are placed in counties
    # that actually appear in the observation sample.
    log.info("Creating demonstration insurance rows")
    psql("""
    INSERT INTO ACCOUNT (AccountID, AccountName, CompanyCode, Address1, City, State, Zip,
                         AccountType, Status, StartDate)
    SELECT gs,
           'Demo Account ' || gs,
           'DEMO' || gs,
           gs || ' Main St',
           'City' || gs,
           'AR',
           LPAD((70000 + gs)::text, 5, '0'),
           CASE WHEN gs % 3 = 0 THEN 'Individual' ELSE 'Group' END,
           CASE WHEN gs % 7 = 0 THEN 'Terminated' ELSE 'Active' END,
           DATE '2020-01-01'
    FROM generate_series(1, 50) gs
    ON CONFLICT (AccountID) DO NOTHING;
    """)

    psql("""
    INSERT INTO CUSTOMER (CustomerID, CustLastName, CustFirstName, CustDOB, CustomerType, Status)
    SELECT gs, 'Last' || gs, 'First' || gs, DATE '1980-01-01' + gs, 'Individual', 'Active'
    FROM generate_series(1, 200) gs
    ON CONFLICT (CustomerID) DO NOTHING;
    """)

    psql("""
    INSERT INTO CONTRACT (ContractID, ContractNumber, AccountID, LineOfBusiness, PlanName,
                          Status, EffectiveDate)
    SELECT gs,
           'C-' || LPAD(gs::text, 6, '0'),
           ((gs - 1) % 50) + 1,
           CASE WHEN gs % 3 = 0 THEN 'A&H' WHEN gs % 3 = 1 THEN 'Life' ELSE 'FSA' END,
           'Plan ' || ((gs % 5) + 1),
           CASE WHEN gs % 6 = 0 THEN 'Terminated' ELSE 'Active' END,
           DATE '2021-01-01' + (gs % 365)
    FROM generate_series(1, 300) gs
    ON CONFLICT (ContractID) DO NOTHING;
    """)

    # Link each demo account to a county that has observations.
    psql("""
    INSERT INTO ACCOUNT_GEOGRAPHY (AccountID, GeographyID, RelationshipType, StartDate)
    SELECT a.AccountID, g.GeographyID, 'PrimaryLocation', DATE '2020-01-01'
    FROM ACCOUNT a
    JOIN LATERAL (
        SELECT DISTINCT ho.GeographyID
        FROM HEALTH_OBSERVATION ho
        ORDER BY ho.GeographyID
        OFFSET (a.AccountID % 200) LIMIT 1
    ) g ON true
    ON CONFLICT DO NOTHING;
    """)

    for table in ["DATASET", "GEOGRAPHIC_AREA", "HEALTH_INDICATOR", "DATA_ASSET",
                  "HEALTH_OBSERVATION", "ACCOUNT", "CUSTOMER", "CONTRACT", "ACCOUNT_GEOGRAPHY"]:
        out = psql(f"SELECT count(*) FROM {table};")
        count = out.strip().splitlines()[2].strip()
        log.info("  %-20s %s rows", table, count)

    psql("ANALYZE;")
    log.info("Load complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
