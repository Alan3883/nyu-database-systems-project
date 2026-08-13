"""Package the Part III submission archive.

Copies deliverables into submission/Mo_p3_su26/, writes a manifest with sizes and
SHA-256 checksums, and creates the zip archive.

Excludes caches, credentials, virtual environments, database volumes, and large
raw datasets. Raw data stays in the working directory; representative samples and
the download script are included instead.

Usage:
    python3 scripts/package_part3.py
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUB = ROOT / "submission"
NAME = "Mo_p3_su26"
DEST = SUB / NAME

# Directories copied whole, with the exclusion rules below applied.
COPY_TREES = [
    ("database", "database"),
    ("workflows", "workflows"),
    ("ml/src", "ml/src"),
    ("ml/tests", "ml/tests"),
    ("ml/models", "ml/models"),
    ("ml/outputs", "ml/outputs"),
    ("architecture/diagrams", "architecture/diagrams"),
    ("architecture/governance", "architecture/governance"),
    ("architecture/cloud_evidence", "architecture/cloud_evidence"),
    ("docs", "docs"),
    ("sample_data", "data_lake/sample_data"),
    ("metadata", "data_lake/metadata"),
    ("curated", "data_lake/curated"),
    ("logs", "logs"),
]

COPY_FILES = [
    ("report/Project_Part_III_Report.docx", "Project_Part_III_Report.docx"),
    ("report/Project_Part_III_Report.md", "Project_Part_III_Report.md"),
    ("report/Project_Part2_Report.pdf", "reference/Project_Part2_Report.pdf"),
    ("ml/README.md", "ml/README.md"),
    ("ml/config.yaml", "ml/config.yaml"),
    ("ml/__init__.py", "ml/__init__.py"),
    ("logical_model/logical_schema.sql", "logical_model/logical_schema.sql"),
    ("logical_model/logical_schema_data_dictionary.csv", "logical_model/logical_schema_data_dictionary.csv"),
    ("logical_model/normalization_review.csv", "logical_model/normalization_review.csv"),
    ("logical_model/Logical_Schema.png", "logical_model/Logical_Schema.png"),
    ("architecture/Reference_Architecture.png", "architecture/Part2_Reference_Architecture.png"),
    ("README.md", "README.md"),
    ("scripts/requirements.txt", "scripts/requirements.txt"),
    ("scripts/download_part2_data.py", "scripts/download_part2_data.py"),
    ("scripts/01_inventory_data.py", "scripts/01_inventory_data.py"),
    ("scripts/02_profile_data.py", "scripts/02_profile_data.py"),
    ("scripts/03_build_curated_data.py", "scripts/03_build_curated_data.py"),
    ("scripts/04_validate_outputs.py", "scripts/04_validate_outputs.py"),
    ("scripts/05_create_submission_samples.py", "scripts/05_create_submission_samples.py"),
    ("scripts/load_curated_to_postgres.py", "scripts/load_curated_to_postgres.py"),
    ("scripts/load_ml_results_to_postgres.py", "scripts/load_ml_results_to_postgres.py"),
    ("scripts/run_performance_tests.py", "scripts/run_performance_tests.py"),
    ("scripts/run_part3_database.sh", "scripts/run_part3_database.sh"),
    ("scripts/run_part3_ml.sh", "scripts/run_part3_ml.sh"),
    ("scripts/run_part3_cloud.sh", "scripts/run_part3_cloud.sh"),
    ("scripts/run_part3_cloud_sandbox.sh", "scripts/run_part3_cloud_sandbox.sh"),
    ("scripts/preflight_cloud.sh", "scripts/preflight_cloud.sh"),
    ("scripts/run_part3_all.sh", "scripts/run_part3_all.sh"),
    ("scripts/validate_part3.py", "scripts/validate_part3.py"),
    ("scripts/package_part3.py", "scripts/package_part3.py"),
]

EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".git", "venv", ".venv",
                "node_modules", ".ipynb_checkpoints"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log.lock", ".DS_Store"}
EXCLUDE_NAMES = {".DS_Store", ".env", "credentials.json", "service_account.json"}


def keep(path: Path) -> bool:
    if any(part in EXCLUDE_DIRS for part in path.parts):
        return False
    if path.name in EXCLUDE_NAMES or path.suffix in EXCLUDE_SUFFIXES:
        return False
    return True


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    print("=" * 68)
    print("PACKAGING PART III SUBMISSION")
    print("=" * 68)

    # Refuse to package if validation fails.
    print("\n[1/5] Running validation")
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_part3.py")],
                            capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout[-2500:])
        print("\nValidation FAILED. Packaging aborted.")
        return 1
    tail = [ln for ln in result.stdout.splitlines() if "checks:" in ln]
    print("  " + (tail[-1] if tail else "validation passed"))

    print("\n[2/5] Building the submission tree")
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)

    copied = 0
    for src_rel, dst_rel in COPY_TREES:
        src = ROOT / src_rel
        if not src.exists():
            print(f"  SKIP missing tree: {src_rel}")
            continue
        for path in src.rglob("*"):
            if not path.is_file() or not keep(path):
                continue
            target = DEST / dst_rel / path.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied += 1

    for src_rel, dst_rel in COPY_FILES:
        src = ROOT / src_rel
        if not src.exists():
            print(f"  SKIP missing file: {src_rel}")
            continue
        target = DEST / dst_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        copied += 1

    print(f"  copied {copied} files")

    # A small excerpt of the unstructured source, not the 14 MB original.
    excerpt = ROOT / "sample_data" / "sample_chr_2025_report_excerpt.pdf"
    if excerpt.exists():
        target = DEST / "data_lake" / "sample_data" / excerpt.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(excerpt, target)

    print("\n[3/5] Final credential scan of the packaged tree")
    import re
    patterns = [re.compile(r"\baf702722ddb1766aac9feb4935bccdd01d975139\b"),
                re.compile(r"-----BEGIN (RSA |EC )?PRIVATE KEY-----"),
                re.compile(r'"type"\s*:\s*"service_account"'),
                re.compile(r"\bAKIA[0-9A-Z]{16}\b")]
    hits = []
    for path in DEST.rglob("*"):
        if not path.is_file() or path.suffix.lower() in {".png", ".pdf", ".docx",
                                                          ".xlsx", ".joblib", ".svg"}:
            continue
        try:
            text = path.read_text(errors="ignore")
        except Exception:  # noqa: BLE001
            continue
        if any(rx.search(text) for rx in patterns):
            hits.append(str(path.relative_to(DEST)))
    if hits:
        print(f"  CREDENTIALS FOUND: {hits}. Packaging aborted.")
        return 1
    print("  clean")

    print("\n[4/5] Writing the manifest")
    rows = []
    for path in sorted(DEST.rglob("*")):
        if path.is_file() and path.name != "submission_manifest.txt":
            rows.append((path.relative_to(DEST).as_posix(),
                         path.stat().st_size, sha256_of(path)))
    manifest = DEST / "submission_manifest.txt"
    with manifest.open("w") as handle:
        handle.write("# Project Part III Submission Manifest\n")
        handle.write("# Alan Mo (bm3883) - CSCI-GA.2433-001\n")
        handle.write(f"# {len(rows)} files\n#\n")
        handle.write("# RelativePath | SizeBytes | SHA256\n")
        for rel, size, digest in rows:
            handle.write(f"{rel} | {size} | {digest}\n")
    print(f"  {len(rows)} files listed")

    print("\n[5/5] Creating the archive")
    archive = SUB / f"{NAME}.zip"
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(DEST.rglob("*")):
            if path.is_file():
                zf.write(path, Path(NAME) / path.relative_to(DEST))

    size_mb = archive.stat().st_size / (1024 * 1024)
    with zipfile.ZipFile(archive) as zf:
        bad = zf.testzip()
        count = len(zf.namelist())
    if bad:
        print(f"  Archive is corrupt at {bad}")
        return 1

    print(f"  {archive}")
    print(f"  {size_mb:.1f} MB, {count} entries, integrity verified")
    print("\n" + "=" * 68)
    print("PACKAGING COMPLETE")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
