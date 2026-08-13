"""Dashboard: the single view of the whole end-to-end system."""

from __future__ import annotations

from flask import Blueprint, render_template
from sqlalchemy import func, select

from ..db import check_connection, read_session
from ..models import Contract, QuoteConversion
from ..services import ml_pipeline_service as ml
from ..services import quote_service, source_monitor_service
from ..services.errors import DomainError

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    ok, db_message = check_connection()
    if not ok:
        return render_template(
            "error.html", title="Database unavailable",
            message=("The application cannot reach PostgreSQL. Start the "
                     "database and reload this page."),
            detail=db_message), 503

    with read_session() as session:
        counts = quote_service.dashboard_counts(session)
        policies = session.execute(
            select(func.count()).select_from(QuoteConversion)).scalar_one()
        contracts = session.execute(
            select(func.count()).select_from(Contract)).scalar_one()

        run = ml.active_run(session)
        status = ml.review_status(session, run.ml_run_id if run else None)
        asset = ml.current_source_asset(session)
        recent_quotes = quote_service.list_quotes(session, limit=8)
        recent_policies = session.scalars(
            select(Contract).order_by(Contract.contract_id.desc()).limit(5)).all()

        # A read-only checksum comparison, so the dashboard states the
        # live source condition rather than the last logged one.
        try:
            source_state = source_monitor_service.check_source(session)
        except DomainError as exc:
            source_state = None
            source_error = str(exc)
        else:
            source_error = None

    return render_template(
        "dashboard.html",
        db_message=db_message,
        counts=counts,
        policies_from_quotes=policies,
        contracts=contracts,
        run=run,
        review=status,
        asset=asset,
        source_state=source_state,
        source_error=source_error,
        recent_quotes=recent_quotes,
        recent_policies=recent_policies,
    )
