"""Watch the DS010 unstructured source and retrain when it changes.

    python3 -m part4.jobs.monitor_unstructured --once
    python3 -m part4.jobs.monitor_unstructured --watch
    python3 -m part4.jobs.monitor_unstructured --once --source <path> --json

One pass does exactly this:

    resolve the active DS010 asset from DATASET / DATA_ASSET
    read the watched file and compute SHA-256
    compare against DATA_ASSET.SHA256
      unchanged -> log it and stop; no ML_RUN is created
      changed   -> copy the bytes to a versioned path, register the new
                   asset, then retrain

The pass is idempotent. Retraining writes the new checksum onto the new
asset row, so an immediately repeated pass sees no change and does
nothing. Running the monitor twice on unchanged input cannot produce two
model runs.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from ..app.config import CONFIG
from ..app.db import check_connection, session_scope
from ..app.services import source_monitor_service as monitor
from ..app.services import retraining_service
from ..app.services.errors import DomainError

LOG_PATH = CONFIG.log_path / "part4_source_monitor.log"


def setup_logging(verbose: bool = True) -> logging.Logger:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(LOG_PATH, mode="a")]
    if verbose:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        handlers=handlers,
        force=True,
    )
    return logging.getLogger("part4.monitor.job")


def run_once(source: Path | None = None, *, actor: str = "source-monitor") -> dict:
    """Execute one detection pass and return a JSON-serialisable summary."""
    log = logging.getLogger("part4.monitor.job")

    ok, message = check_connection()
    if not ok:
        return {"ok": False, "changed": False, "retrained": False,
                "message": f"Database unavailable: {message}"}

    try:
        with session_scope() as session:
            state = monitor.check_source(session, source)
    except DomainError as exc:
        return {"ok": False, "changed": False, "retrained": False,
                "message": str(exc)}

    summary = {
        "ok": True,
        "checked_at": state.checked_at.isoformat(),
        "source": str(state.source_path),
        "source_exists": state.source_exists,
        "current_sha256": state.current_sha256,
        "recorded_sha256": state.recorded_sha256,
        "asset_id": state.asset_id,
        "asset_version": state.asset_version,
        "changed": state.changed,
        "retrained": False,
        "message": state.message,
    }

    if not state.source_exists:
        summary["ok"] = False
        return summary

    if not state.changed:
        return summary

    # --- change detected ---------------------------------------------
    # Version capture is its own transaction. The new raw version is a
    # fact about the lake and stays recorded even if the model work that
    # follows fails.
    try:
        with session_scope() as session:
            asset = monitor.preserve_new_version(
                session, state.source_path, state.current_sha256)
            session.flush()
            asset_id = asset.asset_id
            asset_version = asset.schema_version
            asset_path = asset.relative_path
    except Exception as exc:  # noqa: BLE001
        log.error("Could not preserve the new source version: %s", exc)
        summary["ok"] = False
        summary["message"] = f"Version capture failed: {exc}"
        return summary

    summary["new_asset_id"] = asset_id
    summary["new_asset_version"] = asset_version
    summary["new_asset_path"] = asset_path

    with session_scope() as session:
        asset_obj = session.get(type(asset), asset_id)
        result = retraining_service.retrain(
            asset_obj, source_path=CONFIG.lake_file(asset_path), triggered_by=actor)

    summary["retrained"] = result.ok
    summary["ml_run_id"] = result.ml_run_id
    summary["model_version"] = result.model_version
    summary["selected_k"] = result.selected_k
    summary["n_chunks"] = result.n_chunks
    summary["silhouette"] = result.silhouette
    summary["cluster_sizes"] = result.cluster_sizes
    summary["artifact_dir"] = result.artifact_dir
    summary["message"] = result.message
    summary["error"] = result.error
    summary["ok"] = result.ok
    return summary


def _print(summary: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(summary, indent=2, default=str))
        return
    print("-" * 68)
    print(f"source        : {summary.get('source')}")
    print(f"recorded sha  : {(summary.get('recorded_sha256') or '')[:32]}")
    print(f"current  sha  : {(summary.get('current_sha256') or '')[:32]}")
    print(f"changed       : {summary.get('changed')}")
    print(f"retrained     : {summary.get('retrained')}")
    if summary.get("ml_run_id"):
        print(f"ML_RUN        : {summary['ml_run_id']} "
              f"(version {summary.get('model_version')})")
    print(f"result        : {summary.get('message')}")
    print("-" * 68)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="part4.jobs.monitor_unstructured",
        description="SHA-256 change detection for the DS010 unstructured source.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="run a single pass")
    mode.add_argument("--watch", action="store_true",
                      help="poll continuously until interrupted")
    parser.add_argument("--source", type=Path, default=None,
                        help="override the watched file (used by the tests)")
    parser.add_argument("--interval", type=int, default=CONFIG.poll_interval_seconds,
                        help="seconds between polls in --watch mode")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--actor", default="source-monitor")
    args = parser.parse_args(argv)

    setup_logging(verbose=not args.json)

    if args.once:
        summary = run_once(args.source, actor=args.actor)
        _print(summary, args.json)
        return 0 if summary.get("ok") else 1

    log = logging.getLogger("part4.monitor.job")
    log.info("Watching %s every %ds. Ctrl-C to stop.",
             args.source or CONFIG.watch_path, args.interval)
    try:
        while True:
            summary = run_once(args.source, actor=args.actor)
            _print(summary, args.json)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        log.info("Monitor stopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
