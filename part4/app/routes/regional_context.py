"""Regional research context routes.

Every page rendered here carries the disclaimer. The data is county-level
public health information used for portfolio research, and the interface
is required to say so wherever it appears.
"""

from __future__ import annotations

from flask import Blueprint, render_template

from ..db import read_session
from ..services import ml_pipeline_service as ml
from ..services import regional_context_service as regional

bp = Blueprint("regional", __name__, url_prefix="/regional")


@bp.route("/")
def index():
    with read_session() as session:
        accounts = regional.accounts_with_context(session, limit=40)
        portfolio = regional.portfolio_summary(session, limit=10)
        run = ml.active_run(session)
        mappings = ml.review_status(session, run.ml_run_id if run else None)
    return render_template("regional_context.html", accounts=accounts,
                           portfolio=portfolio, rows=None, account_id=None,
                           run=run, review=mappings,
                           disclaimer=regional.DISCLAIMER)


@bp.route("/<int:account_id>")
def account_context(account_id: int):
    with read_session() as session:
        run = ml.active_run(session)
        rows = regional.account_context(
            session, account_id, ml_run_id=run.ml_run_id if run else None, limit=15)
        accounts = regional.accounts_with_context(session, limit=40)
        portfolio = regional.portfolio_summary(session, limit=10)
        review = ml.review_status(session, run.ml_run_id if run else None)
    return render_template("regional_context.html", accounts=accounts,
                           portfolio=portfolio, rows=rows, account_id=account_id,
                           run=run, review=review,
                           disclaimer=regional.DISCLAIMER)
