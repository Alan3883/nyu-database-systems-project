"""ML pipeline dashboard, source check, and the analyst review interface."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..config import CONFIG
from ..db import read_session, session_scope
from ..models import DataAsset
from ..services import ml_pipeline_service as ml
from ..services import model_review_service as review
from ..services import regional_context_service as regional
from ..services import retraining_service, source_monitor_service
from ..services.errors import DomainError

bp = Blueprint("ml_admin", __name__, url_prefix="/ml")


@bp.route("/")
def dashboard():
    with read_session() as session:
        run = ml.active_run(session)
        runs = ml.run_history(session, limit=10)
        assets = ml.source_asset_versions(session, limit=8)
        status = ml.review_status(session, run.ml_run_id if run else None)
        sizes = ml.cluster_sizes(session, run.ml_run_id) if run else {}
        try:
            state = source_monitor_service.check_source(session)
            error = None
        except DomainError as exc:
            state, error = None, str(exc)
    return render_template("ml_dashboard.html", run=run, runs=runs, assets=assets,
                           review=status, sizes=sizes, state=state, error=error,
                           watch_path=CONFIG.watch_source,
                           registry=CONFIG.model_registry)


@bp.route("/source-check", methods=["POST"])
def source_check():
    """Run one read-only checksum comparison and report the outcome.

    The web action never retrains. Retraining is a pipeline job, run from
    the command line, so a page reload cannot start a training run.
    """
    try:
        with read_session() as session:
            state = source_monitor_service.check_source(session)
        if state.changed:
            flash(f"Source changed. Recorded {state.short_recorded}..., found "
                  f"{state.short_current}.... Run the monitor job to retrain.",
                  "warning")
        else:
            flash(f"No change. SHA-256 {state.short_current}... matches the "
                  f"registered asset. No retraining required.", "success")
    except DomainError as exc:
        flash(str(exc), "error")
    return redirect(url_for("ml_admin.dashboard"))


@bp.route("/runs/<int:ml_run_id>")
def run_review(ml_run_id: int):
    with read_session() as session:
        run = ml.get_run(session, ml_run_id)
        summaries = ml.cluster_summaries(session, ml_run_id)
        sizes = ml.cluster_sizes(session, ml_run_id)
        passages = {s.cluster_id: ml.representative_texts(session, ml_run_id,
                                                          s.cluster_id, limit=2)
                    for s in summaries}
        indicators = regional.indicator_choices(session, limit=400)
        asset = None
        asset_id = run.source_asset_id
        if asset_id:
            asset = session.get(DataAsset, asset_id)
        status = ml.review_status(session, ml_run_id)
        active = ml.active_run(session)
    return render_template("ml_review.html", run=run, summaries=summaries,
                           sizes=sizes, passages=passages, indicators=indicators,
                           asset=asset, review=status,
                           is_active=bool(active and active.ml_run_id == ml_run_id))


@bp.route("/runs/<int:ml_run_id>/clusters/<int:cluster_id>/review", methods=["POST"])
def submit_review(ml_run_id: int, cluster_id: int):
    form = request.form
    try:
        with session_scope() as session:
            review.review_cluster(
                session, ml_run_id, cluster_id,
                reviewer=form.get("reviewer", ""),
                decision=form.get("decision", "approve"),
                interpretation=form.get("interpretation"))
        flash(f"Cluster {cluster_id} review recorded.", "success")
    except DomainError as exc:
        flash(str(exc), "error")
    return redirect(url_for("ml_admin.run_review", ml_run_id=ml_run_id))


@bp.route("/runs/<int:ml_run_id>/clusters/<int:cluster_id>/map", methods=["POST"])
def submit_mapping(ml_run_id: int, cluster_id: int):
    form = request.form
    try:
        indicator_id = int(form.get("indicator_id") or 0)
    except ValueError:
        flash("Select a health indicator from the list.", "error")
        return redirect(url_for("ml_admin.run_review", ml_run_id=ml_run_id))
    try:
        with session_scope() as session:
            review.approve_indicator_mapping(
                session, ml_run_id, cluster_id,
                indicator_id=indicator_id,
                approver=form.get("approver", ""),
                notes=form.get("notes"))
        flash(f"Cluster {cluster_id} mapped to an approved health indicator.",
              "success")
    except DomainError as exc:
        flash(str(exc), "error")
    return redirect(url_for("ml_admin.run_review", ml_run_id=ml_run_id))


@bp.route("/mappings/<int:mapping_id>/retire", methods=["POST"])
def retire_mapping(mapping_id: int):
    run_id = request.form.get("ml_run_id", type=int)
    try:
        with session_scope() as session:
            review.retire_mapping(session, mapping_id,
                                  actor=request.form.get("actor", ""))
        flash("Mapping retired. The audit record was kept.", "success")
    except DomainError as exc:
        flash(str(exc), "error")
    return redirect(url_for("ml_admin.run_review", ml_run_id=run_id))
