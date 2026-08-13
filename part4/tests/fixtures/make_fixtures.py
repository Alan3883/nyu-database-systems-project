"""Build the retraining test fixtures from the DS010 source.

    python3 part4/tests/fixtures/make_fixtures.py

The retraining tests need an unstructured document whose bytes differ
from the registered DS010 asset. Editing the raw file would destroy the
immutable source, so the fixtures are derived copies written into
part4/tests/fixtures/ and never into the raw zone.

  chr_2025_report_revised.pdf   pages 1-12 of the original, standing in
                                for a revised edition of the report
  chr_2025_report_partial.pdf   pages 1-9, used for the controlled
                                failure test

Both keep real report text, so the pipeline that runs against them is
doing the same work it does on the real source, not clustering filler.
"""

from __future__ import annotations

import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter

WORKSPACE = Path(__file__).resolve().parents[3]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from part4.app.config import CONFIG  # noqa: E402

SOURCE = CONFIG.watch_path
HERE = Path(__file__).resolve().parent

VARIANTS = {
    "chr_2025_report_revised.pdf": range(0, 12),
    "chr_2025_report_partial.pdf": range(0, 9),
}


def main() -> int:
    if not SOURCE.exists():
        print(f"DS010 source not found at {SOURCE}", file=sys.stderr)
        return 1

    reader = PdfReader(str(SOURCE))
    for name, pages in VARIANTS.items():
        target = HERE / name
        if target.exists():
            print(f"exists  {name}")
            continue
        writer = PdfWriter()
        for index in pages:
            if index < len(reader.pages):
                writer.add_page(reader.pages[index])
        with target.open("wb") as handle:
            writer.write(handle)
        print(f"created {name}  {target.stat().st_size:,} bytes  "
              f"{len(writer.pages)} pages")

    # The raw source must be unchanged by this script.
    print(f"source  {SOURCE.name} {SOURCE.stat().st_size:,} bytes (untouched)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
