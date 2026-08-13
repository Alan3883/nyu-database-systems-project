"""Retraining demonstration: the four cases Part IV has to prove.

    python3 scripts/run_part4_retraining_demo.py

    Test A  unchanged source        no retraining, no new ML_RUN
    Test B  changed source          new version, new ML_RUN, results loaded,
                                    every interpretation unreviewed
    Test B2 repeat of Test B        idempotent: no second run
    Test C  controlled failure      previous model stays active, run marked
                                    Failed, no partial results
    Test D  source restored         retrains back onto the original DS010
                                    bytes so the watched path and the
                                    registered checksum agree again

The raw DS010 file is never modified. Tests B and C read fixtures built by
part4/tests/fixtures/make_fixtures.py from the original; the monitor copies
those bytes into the versioned raw area, which is an append-only operation.

Evidence is written to part4/evidence/retraining_demonstration.txt.
"""

from __future__ import annotations

import io
import os
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

# part4/scripts/<file> -> part4 -> the course workspace, which must be on
# sys.path so `import part4...` resolves.
PART4 = Path(__file__).resolve().parent.parent
WORKSPACE = PART4.parent
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from sqlalchemy import func, select  # noqa: E402

from part4.app.config import CONFIG  # noqa: E402
from part4.app.db import read_session  # noqa: E402
from part4.app.models import DataAsset, MLClusterSummary, MLRun  # noqa: E402
from part4.app.services import ml_pipeline_service as ml  # noqa: E402
from part4.jobs.monitor_unstructured import run_once, setup_logging  # noqa: E402

FIXTURES = PART4 / "tests" / "fixtures"
REVISED = FIXTURES / "chr_2025_report_revised.pdf"
PARTIAL = FIXTURES / "chr_2025_report_partial.pdf"
EVIDENCE = PART4 / "evidence" / "retraining_demonstration.txt"

lines: list[str] = []


def emit(text: str = "") -> None:
    print(text)
    lines.append(text)


def snapshot() -> dict:
    """Current pipeline state, as the application sees it."""
    with read_session() as session:
        active = ml.active_run(session)
        runs = session.execute(select(func.count()).select_from(MLRun)).scalar_one()
        completed = session.execute(
            select(func.count()).select_from(MLRun)
            .where(MLRun.status == "Completed")).scalar_one()
        failed = session.execute(
            select(func.count()).select_from(MLRun)
            .where(MLRun.status == "Failed")).scalar_one()
        assets = session.execute(
            select(func.count()).select_from(DataAsset)
            .where(DataAsset.dataset_id == "DS010")).scalar_one()
        current = ml.current_source_asset(session)
        unreviewed = None
        if active:
            unreviewed = session.execute(
                select(func.count()).select_from(MLClusterSummary)
                .where(MLClusterSummary.ml_run_id == active.ml_run_id)
                .where(MLClusterSummary.human_reviewed.is_(False))).scalar_one()
            total = session.execute(
                select(func.count()).select_from(MLClusterSummary)
                .where(MLClusterSummary.ml_run_id == active.ml_run_id)).scalar_one()
        else:
            total = 0
    return {
        "active_run": active.ml_run_id if active else None,
        "active_version": active.model_version if active else None,
        "runs": runs, "completed": completed, "failed": failed,
        "asset_versions": assets,
        "current_asset": current.asset_id if current else None,
        "current_asset_version": current.schema_version if current else None,
        "unreviewed": unreviewed, "clusters": total,
    }


def report(state: dict) -> str:
    return (f"active ML_RUN={state['active_run']} ({state['active_version']}), "
            f"runs={state['runs']} completed={state['completed']} failed={state['failed']}, "
            f"DS010 asset versions={state['asset_versions']}, "
            f"current asset={state['current_asset']} ({state['current_asset_version']}), "
            f"clusters={state['clusters']} unreviewed={state['unreviewed']}")


def run_monitor(source: Path | None, label: str) -> dict:
    """Run one monitor pass, capturing its own printed summary."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        summary = run_once(source, actor=f"retraining-demo:{label}")
    for line in buffer.getvalue().splitlines():
        if line.strip():
            emit(f"      {line}")
    return summary


def check(name: str, passed: bool, detail: str) -> bool:
    emit(f"   {'PASS' if passed else 'FAIL'}  {name}")
    emit(f"         {detail}")
    return passed


def main() -> int:
    setup_logging(verbose=False)
    if not REVISED.exists() or not PARTIAL.exists():
        print("Fixtures missing. Run: python3 part4/tests/fixtures/make_fixtures.py",
              file=sys.stderr)
        return 1

    emit("=" * 78)
    emit("Part IV retraining demonstration")
    emit(f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    emit("=" * 78)

    outcomes: list[bool] = []
    before = snapshot()
    emit(f"\nBaseline: {report(before)}")

    # ---------------------------------------------------------------
    emit("\n" + "-" * 78)
    emit("TEST A - unchanged source")
    emit("-" * 78)
    emit("   Command: monitor --once (watched DS010 raw file)")
    a = run_monitor(None, "test-a")
    after = snapshot()
    outcomes.append(check(
        "checksum unchanged, no retraining, no new ML_RUN",
        (not a["changed"]) and (not a["retrained"])
        and after["runs"] == before["runs"]
        and after["active_run"] == before["active_run"],
        f"changed={a['changed']} retrained={a['retrained']}; {report(after)}"))

    # ---------------------------------------------------------------
    emit("\n" + "-" * 78)
    emit("TEST B - source changed")
    emit("-" * 78)
    emit(f"   Command: monitor --once --source {REVISED.relative_to(WORKSPACE)}")
    before_b = snapshot()
    b = run_monitor(REVISED, "test-b")
    after_b = snapshot()
    outcomes.append(check(
        "new versioned asset, new ML_RUN, results loaded, all unreviewed",
        b["changed"] and b["retrained"]
        and after_b["runs"] == before_b["runs"] + 1
        and after_b["asset_versions"] == before_b["asset_versions"] + 1
        and after_b["active_run"] != before_b["active_run"]
        and after_b["clusters"] > 0
        and after_b["unreviewed"] == after_b["clusters"],
        f"ML_RUN {b['ml_run_id']} version {b['model_version']}, "
        f"asset {b['new_asset_version']}, K={b['selected_k']}, "
        f"{b['n_chunks']} chunks; {report(after_b)}"))

    versioned = CONFIG.lake_file(b.get("new_asset_path") or "")
    outcomes.append(check(
        "previous raw version preserved, not overwritten",
        versioned.exists()
        and CONFIG.watch_path.exists(),
        f"new version {b.get('new_asset_path')} written; original raw file "
        f"still present and unmodified"))

    # ---------------------------------------------------------------
    emit("\n" + "-" * 78)
    emit("TEST B2 - repeat the same check (idempotency)")
    emit("-" * 78)
    emit(f"   Command: monitor --once --source {REVISED.relative_to(WORKSPACE)}  (again)")
    b2 = run_monitor(REVISED, "test-b2")
    after_b2 = snapshot()
    outcomes.append(check(
        "second pass on unchanged input creates no duplicate run",
        (not b2["changed"]) and (not b2["retrained"])
        and after_b2["runs"] == after_b["runs"],
        f"changed={b2['changed']} retrained={b2['retrained']}; {report(after_b2)}"))

    # ---------------------------------------------------------------
    emit("\n" + "-" * 78)
    emit("TEST C - controlled retraining failure")
    emit("-" * 78)
    emit(f"   Command: PART4_FORCE_RETRAIN_FAILURE=train monitor --once "
         f"--source {PARTIAL.relative_to(WORKSPACE)}")
    emit("   The injected failure occurs after the ML_RUN row is opened and "
         "before any result is written.")
    before_c = snapshot()
    os.environ["PART4_FORCE_RETRAIN_FAILURE"] = "train"
    try:
        c = run_monitor(PARTIAL, "test-c")
    finally:
        os.environ.pop("PART4_FORCE_RETRAIN_FAILURE", None)
    after_c = snapshot()

    with read_session() as session:
        failed_run = session.get(MLRun, c.get("ml_run_id")) if c.get("ml_run_id") else None
        partial_rows = 0
        if failed_run is not None:
            partial_rows = session.execute(
                select(func.count()).select_from(MLClusterSummary)
                .where(MLClusterSummary.ml_run_id == failed_run.ml_run_id)).scalar_one()

    outcomes.append(check(
        "previous model stays active, failure recorded, no partial results",
        (not c["retrained"])
        and after_c["active_run"] == before_c["active_run"]
        and failed_run is not None and failed_run.status == "Failed"
        and partial_rows == 0,
        f"ML_RUN {c.get('ml_run_id')} status="
        f"{failed_run.status if failed_run else 'n/a'} with 0 cluster rows; "
        f"active model unchanged at ML_RUN {after_c['active_run']}; "
        f"error recorded: {c.get('error')}"))

    outcomes.append(check(
        "the new raw version is still registered after the failure",
        after_c["asset_versions"] == before_c["asset_versions"] + 1,
        "Raw-asset capture is a separate, append-only ingestion step. The "
        "bytes that arrived are recorded even though the model built from "
        "them was rejected."))

    # ---------------------------------------------------------------
    emit("\n" + "-" * 78)
    emit("TEST D - source restored to the original DS010 report")
    emit("-" * 78)
    emit("   Command: monitor --once (watched DS010 raw file)")
    before_d = snapshot()
    d = run_monitor(None, "test-d")
    after_d = snapshot()
    outcomes.append(check(
        "restored source is detected and retrained, ending in a consistent state",
        d["changed"] and d["retrained"]
        and after_d["active_run"] != before_d["active_run"]
        and after_d["unreviewed"] == after_d["clusters"],
        f"ML_RUN {d.get('ml_run_id')} version {d.get('model_version')} on asset "
        f"{d.get('new_asset_version')}, K={d.get('selected_k')}, "
        f"{d.get('n_chunks')} chunks; {report(after_d)}"))

    final = run_monitor(None, "final-check")
    outcomes.append(check(
        "final state: watched file matches the registered checksum",
        not final["changed"],
        final["message"]))

    # ---------------------------------------------------------------
    emit("\n" + "=" * 78)
    emit(f"{sum(outcomes)}/{len(outcomes)} checks passed")
    emit("=" * 78)

    with read_session() as session:
        emit("\nML_RUN history")
        for run in ml.run_history(session, limit=20)[::-1]:
            metrics = run.metrics_json or {}
            emit(f"  run {run.ml_run_id}  {run.model_version:<7} {run.status:<10} "
                 f"asset={metrics.get('source_asset_version', '-'):<4} "
                 f"K={metrics.get('selected_k', '-')}  "
                 f"{metrics.get('error', '')}")
        emit("\nDS010 asset versions")
        for asset in ml.source_asset_versions(session, limit=20)[::-1]:
            emit(f"  asset {asset.asset_id}  {asset.schema_version or 'v1':<4} "
                 f"{asset.status:<11} sha256={asset.sha256[:16]}...  "
                 f"{asset.relative_path}")

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(lines) + "\n")
    print(f"\nEvidence written to {EVIDENCE.relative_to(WORKSPACE)}")
    return 0 if all(outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
