"""Retrain the DS010 theme model on demand.

    python3 -m part4.jobs.retrain_model --current
    python3 -m part4.jobs.retrain_model --asset-id 12

Change detection is the monitor's job. This entry point exists for the
case where the source has not changed but the model must be rebuilt: a
configuration change, a library upgrade, or a reproducibility check.

The same guarantees apply as in the monitored path. A failure is written
as a Failed ML_RUN, the previously completed run stays active, and no
partial results are stored.
"""

from __future__ import annotations

import argparse
import json
import sys

from ..app.config import CONFIG
from ..app.db import check_connection, session_scope
from ..app.models import DataAsset
from ..app.services import retraining_service, source_monitor_service
from .monitor_unstructured import setup_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="part4.jobs.retrain_model",
        description="Retrain the DS010 theme model against a stored source asset.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--current", action="store_true",
                        help="use the current DS010 asset version")
    target.add_argument("--asset-id", type=int, help="use a specific DATA_ASSET row")
    parser.add_argument("--actor", default="manual-retrain")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    setup_logging(verbose=not args.json)

    ok, message = check_connection()
    if not ok:
        print(f"Database unavailable: {message}", file=sys.stderr)
        return 1

    with session_scope() as session:
        if args.current:
            asset = source_monitor_service.resolve_active_asset(session)
        else:
            asset = session.get(DataAsset, args.asset_id)
            if asset is None:
                print(f"DATA_ASSET {args.asset_id} does not exist.", file=sys.stderr)
                return 1
        asset_id = asset.asset_id
        asset_path = asset.relative_path

    with session_scope() as session:
        asset = session.get(DataAsset, asset_id)
        result = retraining_service.retrain(
            asset, source_path=CONFIG.lake_file(asset_path), triggered_by=args.actor)

    if args.json:
        print(json.dumps(result.__dict__, indent=2, default=str))
    else:
        print(result.message)
        if result.ok:
            print(f"  ML_RUN        : {result.ml_run_id}")
            print(f"  model version : {result.model_version}")
            print(f"  chunks        : {result.n_chunks}")
            print(f"  selected K    : {result.selected_k}")
            print(f"  silhouette    : {result.silhouette}")
            print(f"  cluster sizes : {result.cluster_sizes}")
            print(f"  artifacts     : {result.artifact_dir}")
        else:
            print(f"  error         : {result.error}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
