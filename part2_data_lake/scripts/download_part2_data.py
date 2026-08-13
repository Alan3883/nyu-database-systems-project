#!/usr/bin/env python3
"""Download the public datasets used by Database Systems Project Part II.

The script uses only the Python standard library. It creates the raw-data folders,
downloads the CDC and County Health Rankings files, requests selected ACS 2024
5-year subject tables at county level, and writes a download manifest.

Census API calls currently require an API key. Provide it with either:
    export CENSUS_API_KEY="your_key"
or:
    python3 download_part2_data.py --census-key "your_key"
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

USER_AGENT = "NYU-Database-Systems-Project-Part2/1.0"
CHUNK_SIZE = 1024 * 1024
MAX_RETRIES = 3
TIMEOUT_SECONDS = 180


@dataclass(frozen=True)
class DownloadSpec:
    dataset_id: str
    name: str
    url: str
    relative_path: str
    source_org: str
    geographic_level: str
    main_subject: str
    key_fields: str
    related_eda_entity: str


STATIC_DOWNLOADS = [
    DownloadSpec(
        dataset_id="DS001",
        name="CDC PLACES County Data, 2025 release",
        url="https://data.cdc.gov/api/views/swc5-untb/rows.csv?accessType=DOWNLOAD",
        relative_path="raw/cdc_places_county/places_county_2025.csv",
        source_org="Centers for Disease Control and Prevention",
        geographic_level="County",
        main_subject="Chronic disease outcomes and health risk behaviors",
        key_fields="StateAbbr, CountyName, CountyFIPS, MeasureId",
        related_eda_entity="ACCOUNT, CUSTOMER, CONTRACT",
    ),
    DownloadSpec(
        dataset_id="DS002",
        name="U.S. Chronic Disease Indicators",
        url="https://data.cdc.gov/api/views/hksd-2xuw/rows.csv?accessType=DOWNLOAD",
        relative_path="raw/cdc_chronic_disease_indicators/us_chronic_disease_indicators.csv",
        source_org="Centers for Disease Control and Prevention",
        geographic_level="State/Territory",
        main_subject="Chronic disease indicators",
        key_fields="LocationAbbr, LocationID, TopicID, QuestionID, YearStart",
        related_eda_entity="ACCOUNT, CONTRACT",
    ),
    DownloadSpec(
        dataset_id="DS003",
        name="2025 County Health Release National Data",
        url="https://www.countyhealthrankings.org/sites/default/files/media/document/2025%20County%20Health%20Rankings%20Data%20-%20v4.xlsx",
        relative_path="raw/county_health_rankings/county_health_rankings_2025.xlsx",
        source_org="County Health Rankings & Roadmaps",
        geographic_level="County/State/National",
        main_subject="Health outcomes, behaviors, clinical care, social and economic factors",
        key_fields="FIPS, State Abbreviation, County Name",
        related_eda_entity="ACCOUNT, CUSTOMER, CONTRACT",
    ),
    DownloadSpec(
        dataset_id="DS004",
        name="2025 CHR CSV Analytic Data",
        url="https://www.countyhealthrankings.org/sites/default/files/media/document/analytic_data2025_v3.csv",
        relative_path="raw/county_health_rankings/county_health_rankings_analytic_2025.csv",
        source_org="County Health Rankings & Roadmaps",
        geographic_level="County/State",
        main_subject="Analysis-ready county health measures",
        key_fields="fipscode, statecode, county",
        related_eda_entity="ACCOUNT, CUSTOMER, CONTRACT",
    ),
    DownloadSpec(
        dataset_id="DS005",
        name="2025 County Health Rankings Data Dictionary",
        url="https://www.countyhealthrankings.org/sites/default/files/media/document/DataDictionary_2025.xlsx",
        relative_path="raw/county_health_rankings/county_health_rankings_data_dictionary_2025.xlsx",
        source_org="County Health Rankings & Roadmaps",
        geographic_level="Documentation",
        main_subject="Definitions and metadata for County Health Rankings measures",
        key_fields="Variable Name",
        related_eda_entity="DATASET_METADATA",
    ),
]

ACS_GROUPS = [
    ("DS006", "S0101", "Age and Sex", "Age, sex, and population profile"),
    ("DS007", "S1901", "Income", "Household income and earnings"),
    ("DS008", "S1701", "Poverty", "Poverty status and population groups"),
    ("DS009", "S2701", "Health Insurance", "Health insurance coverage"),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def human_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def request_bytes(url: str, *, retries: int = MAX_RETRIES) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError) as error:
            last_error = error
            if attempt < retries:
                delay = 2 ** (attempt - 1)
                print(f"  Request failed ({error}); retrying in {delay}s...", file=sys.stderr)
                time.sleep(delay)
    raise RuntimeError(f"Failed after {retries} attempts: {url}") from last_error


def download_stream(url: str, destination: Path, *, overwrite: bool) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not overwrite:
        size = destination.stat().st_size
        return {
            "status": "skipped_existing",
            "bytes": size,
            "sha256": sha256_file(destination),
        }

    temporary = destination.with_suffix(destination.suffix + ".part")
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=TIMEOUT_SECONDS) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output, length=CHUNK_SIZE)
            temporary.replace(destination)
            size = destination.stat().st_size
            return {
                "status": "downloaded",
                "bytes": size,
                "sha256": sha256_file(destination),
            }
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            last_error = error
            temporary.unlink(missing_ok=True)
            if attempt < MAX_RETRIES:
                delay = 2 ** (attempt - 1)
                print(f"  Download failed ({error}); retrying in {delay}s...", file=sys.stderr)
                time.sleep(delay)
    raise RuntimeError(f"Failed after {MAX_RETRIES} attempts: {url}") from last_error


def write_json_as_csv(payload: bytes, destination: Path) -> int:
    try:
        rows = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Census API did not return valid JSON") from error

    if not isinstance(rows, list) or not rows or not isinstance(rows[0], list):
        raise RuntimeError(f"Unexpected Census API response: {rows!r}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)
    return max(0, len(rows) - 1)


def download_acs_group(
    output_root: Path,
    dataset_id: str,
    group: str,
    label: str,
    subject: str,
    api_key: str,
    *,
    overwrite: bool,
) -> tuple[DownloadSpec, dict[str, Any]]:
    query = {
        "get": f"NAME,group({group})",
        "for": "county:*",
        "key": api_key,
    }
    url = "https://api.census.gov/data/2024/acs/acs5/subject?" + urlencode(query)
    relative_path = f"raw/census_acs_5year/acs5_2024_{group}_{label.lower().replace(' ', '_')}_county.csv"
    destination = output_root / relative_path

    spec = DownloadSpec(
        dataset_id=dataset_id,
        name=f"2024 ACS 5-Year Subject Table {group}: {label}",
        url=url,
        relative_path=relative_path,
        source_org="U.S. Census Bureau",
        geographic_level="County",
        main_subject=subject,
        key_fields="state, county, NAME",
        related_eda_entity="ACCOUNT, CUSTOMER, REGION",
    )

    if destination.exists() and not overwrite:
        result = {
            "status": "skipped_existing",
            "bytes": destination.stat().st_size,
            "sha256": sha256_file(destination),
        }
        return spec, result

    payload = request_bytes(url)
    row_count = write_json_as_csv(payload, destination)
    result = {
        "status": "downloaded",
        "bytes": destination.stat().st_size,
        "sha256": sha256_file(destination),
        "data_rows": row_count,
    }
    return spec, result


def write_catalog(output_root: Path, specs: list[DownloadSpec]) -> None:
    catalog_path = output_root / "metadata/dataset_catalog.csv"
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "DatasetID",
        "DatasetName",
        "SourceOrganization",
        "SourceURL",
        "FileFormat",
        "DataType",
        "GeographicLevel",
        "TimePeriod",
        "MainSubject",
        "KeyFields",
        "RelatedEDAEntity",
        "StorageZone",
        "UpdateFrequency",
        "Notes",
    ]
    with catalog_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for spec in specs:
            suffix = Path(spec.relative_path).suffix.lower().lstrip(".")
            time_period = "2025" if "2025" in spec.name else "2024" if "2024" in spec.name else "Multiple years"
            writer.writerow(
                {
                    "DatasetID": spec.dataset_id,
                    "DatasetName": spec.name,
                    "SourceOrganization": spec.source_org,
                    "SourceURL": spec.url,
                    "FileFormat": suffix.upper(),
                    "DataType": "Structured or semi-structured",
                    "GeographicLevel": spec.geographic_level,
                    "TimePeriod": time_period,
                    "MainSubject": spec.main_subject,
                    "KeyFields": spec.key_fields,
                    "RelatedEDAEntity": spec.related_eda_entity,
                    "StorageZone": str(Path(spec.relative_path).parent),
                    "UpdateFrequency": "Annual or source-defined",
                    "Notes": "Downloaded from the official source for Project Part II.",
                }
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parents[1]),
        help="Data lake root directory (default: the parent of scripts/).",
    )
    parser.add_argument(
        "--census-key",
        default=os.environ.get("CENSUS_API_KEY", ""),
        help="U.S. Census API key. Can also be set with CENSUS_API_KEY.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Replace files that already exist.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned files without downloading.")
    parser.add_argument("--skip-census", action="store_true", help="Skip all ACS Census API requests.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_root = Path(args.output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    planned_specs = list(STATIC_DOWNLOADS)
    if not args.skip_census:
        for dataset_id, group, label, subject in ACS_GROUPS:
            planned_specs.append(
                DownloadSpec(
                    dataset_id=dataset_id,
                    name=f"2024 ACS 5-Year Subject Table {group}: {label}",
                    url=f"https://api.census.gov/data/2024/acs/acs5/subject?get=NAME,group({group})&for=county:*&key=<CENSUS_API_KEY>",
                    relative_path=f"raw/census_acs_5year/acs5_2024_{group}_{label.lower().replace(' ', '_')}_county.csv",
                    source_org="U.S. Census Bureau",
                    geographic_level="County",
                    main_subject=subject,
                    key_fields="state, county, NAME",
                    related_eda_entity="ACCOUNT, CUSTOMER, REGION",
                )
            )

    write_catalog(output_root, planned_specs)

    if args.dry_run:
        print(f"Output directory: {output_root}")
        for spec in planned_specs:
            print(f"- {spec.dataset_id}: {spec.relative_path}\n  {spec.url}")
        return 0

    manifest: dict[str, Any] = {
        "created_at_utc": utc_now(),
        "output_root": str(output_root),
        "downloads": [],
    }

    for spec in STATIC_DOWNLOADS:
        destination = output_root / spec.relative_path
        print(f"Downloading {spec.dataset_id}: {spec.name}")
        try:
            result = download_stream(spec.url, destination, overwrite=args.overwrite)
            print(f"  {result['status']}: {destination} ({human_bytes(result['bytes'])})")
            manifest["downloads"].append({**asdict(spec), **result})
        except Exception as error:  # continue so one source does not block all others
            print(f"  ERROR: {error}", file=sys.stderr)
            manifest["downloads"].append({**asdict(spec), "status": "error", "error": str(error)})

    if args.skip_census:
        print("Skipping ACS Census downloads (--skip-census).")
    elif not args.census_key:
        message = (
            "ACS downloads were skipped because no Census API key was supplied. "
            "Request a free key at https://api.census.gov/data/key_signup.html, then set "
            "CENSUS_API_KEY or use --census-key."
        )
        print(message, file=sys.stderr)
        manifest["downloads"].append({"dataset_id": "DS006-DS009", "status": "skipped_missing_census_key", "note": message})
    else:
        for dataset_id, group, label, subject in ACS_GROUPS:
            print(f"Downloading {dataset_id}: ACS {group} ({label})")
            try:
                spec, result = download_acs_group(
                    output_root,
                    dataset_id,
                    group,
                    label,
                    subject,
                    args.census_key,
                    overwrite=args.overwrite,
                )
                print(f"  {result['status']}: {output_root / spec.relative_path} ({human_bytes(result['bytes'])})")
                manifest["downloads"].append({**asdict(spec), **result})
            except Exception as error:
                print(f"  ERROR: {error}", file=sys.stderr)
                manifest["downloads"].append(
                    {
                        "dataset_id": dataset_id,
                        "name": f"2024 ACS 5-Year Subject Table {group}: {label}",
                        "status": "error",
                        "error": str(error),
                    }
                )

    manifest_path = output_root / "metadata/download_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    error_count = sum(item.get("status") == "error" for item in manifest["downloads"])
    print(f"Manifest written to {manifest_path}")
    if error_count:
        print(f"Completed with {error_count} download error(s). Review the manifest.", file=sys.stderr)
        return 1
    print("All requested available downloads completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
