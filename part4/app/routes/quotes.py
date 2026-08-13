"""Quote workflow routes: list, create, detail, coverage, transitions, payment."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..db import read_session, session_scope
from ..services import ml_pipeline_service as ml
from ..services import policy_service, quote_service, regional_context_service
from ..services.errors import DomainError, ValidationError

bp = Blueprint("quotes", __name__, url_prefix="/quotes")

STATUSES = ("Draft", "Submitted", "Rated", "Presented", "Accepted",
            "Rejected", "Expired", "Converted")


def _decimal(raw: str | None, field: str) -> Decimal | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        return Decimal(str(raw).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(f"{field} must be a number.") from exc


def _date(raw: str | None, field: str, *, required: bool = False) -> date | None:
    if not raw or not raw.strip():
        if required:
            raise ValidationError(f"{field} is required.")
        return None
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationError(f"{field} must be a date in YYYY-MM-DD form.") from exc


@bp.route("/")
def list_quotes():
    status = request.args.get("status") or None
    if status and status not in STATUSES:
        status = None
    with read_session() as session:
        quotes = quote_service.list_quotes(session, status=status, limit=50)
        counts = quote_service.dashboard_counts(session)
    return render_template("quote_list.html", quotes=quotes, counts=counts,
                           statuses=STATUSES, selected=status)


@bp.route("/new", methods=["GET", "POST"])
def new_quote():
    if request.method == "GET":
        with read_session() as session:
            customers = quote_service.list_customers(session, limit=100)
            accounts = quote_service.list_accounts(session, limit=100)
        return render_template(
            "quote_new.html", customers=customers, accounts=accounts,
            product_lines=quote_service.PRODUCT_LINES,
            today=date.today().isoformat(),
            next_year=(date.today() + timedelta(days=365)).isoformat())

    form = request.form
    try:
        customer_id = int(form.get("customer_id") or 0)
        account_id = int(form["account_id"]) if form.get("account_id") else None
        actor = (form.get("actor") or "").strip()
        if not actor:
            raise ValidationError("Your name is required so the audit trail "
                                  "records who created the quote.")
        with session_scope() as session:
            quote = quote_service.create_quote(
                session,
                customer_id=customer_id,
                account_id=account_id,
                product_line=form.get("product_line", ""),
                requested_date=_date(form.get("requested_date"), "Requested date",
                                     required=True),
                effective_date=_date(form.get("effective_date"), "Effective date"),
                expiration_date=_date(form.get("expiration_date"), "Expiration date"),
                actor=actor,
            )
            # Optional first coverage line, entered on the same form so a
            # usable quote exists after one submission.
            if (form.get("coverage_name") or "").strip():
                quote_service.add_coverage(
                    session, quote.quote_id,
                    coverage_name=form["coverage_name"],
                    coverage_limit=_decimal(form.get("coverage_limit"), "Coverage limit"),
                    deductible=_decimal(form.get("deductible"), "Deductible"))
            quote_id = quote.quote_id
            quote_number = quote.quote_number
    except DomainError as exc:
        flash(str(exc), "error")
        return redirect(url_for("quotes.new_quote"))
    except ValueError:
        flash("Customer and account must be selected from the lists.", "error")
        return redirect(url_for("quotes.new_quote"))

    flash(f"Quote {quote_number} created as a draft.", "success")
    return redirect(url_for("quotes.quote_detail", quote_id=quote_id))


@bp.route("/<int:quote_id>")
def quote_detail(quote_id: int):
    with read_session() as session:
        quote = quote_service.get_quote(session, quote_id)
        run = ml.active_run(session)
        context = []
        if quote.account_id:
            context = regional_context_service.account_context(
                session, quote.account_id,
                ml_run_id=run.ml_run_id if run else None, limit=8)
        allowed = sorted(quote_service.ALLOWED_TRANSITIONS.get(quote.quote_status, set()))
        conversion = quote.conversion
    return render_template(
        "quote_detail.html", quote=quote, context=context, run=run,
        allowed=allowed, conversion=conversion,
        disclaimer=regional_context_service.DISCLAIMER)


@bp.route("/<int:quote_id>/coverage", methods=["POST"])
def add_coverage(quote_id: int):
    form = request.form
    try:
        with session_scope() as session:
            quote_service.add_coverage(
                session, quote_id,
                coverage_name=form.get("coverage_name", ""),
                coverage_limit=_decimal(form.get("coverage_limit"), "Coverage limit"),
                deductible=_decimal(form.get("deductible"), "Deductible"))
        flash("Coverage added and the estimated premium recalculated.", "success")
    except DomainError as exc:
        flash(str(exc), "error")
    return redirect(url_for("quotes.quote_detail", quote_id=quote_id))


@bp.route("/<int:quote_id>/transition", methods=["POST"])
def transition(quote_id: int):
    new_status = request.form.get("new_status", "")
    actor = request.form.get("actor", "")
    reason = request.form.get("reason") or None
    try:
        with session_scope() as session:
            quote_service.transition(session, quote_id, new_status,
                                     actor=actor, reason=reason)
        flash(f"Quote moved to {new_status}.", "success")
    except DomainError as exc:
        flash(str(exc), "error")
    return redirect(url_for("quotes.quote_detail", quote_id=quote_id))


@bp.route("/<int:quote_id>/payment", methods=["POST"])
def payment(quote_id: int):
    form = request.form
    try:
        with session_scope() as session:
            quote = quote_service.get_quote(session, quote_id, eager=False)
            amount = _decimal(form.get("amount"), "Amount")
            auth = quote_service.authorize_payment(
                session, quote_id,
                method=form.get("method", "Card"),
                amount=amount if amount is not None else (quote.estimated_premium or 0),
                actor=form.get("actor", "web-user"))
            reference = auth.authorization_reference
        flash(f"Payment authorized: {reference}. No card data was stored.", "success")
    except DomainError as exc:
        flash(str(exc), "error")
    return redirect(url_for("quotes.quote_detail", quote_id=quote_id))


@bp.route("/<int:quote_id>/record-context", methods=["POST"])
def record_context(quote_id: int):
    """Log that regional research context was consulted on this quote."""
    try:
        with session_scope() as session:
            run = ml.active_run(session)
            quote = quote_service.get_quote(session, quote_id, eager=False)
            rows = regional_context_service.account_context(
                session, quote.account_id,
                ml_run_id=run.ml_run_id if run else None, limit=3)
            for row in rows:
                quote_service.record_regional_research_factor(
                    session, quote_id,
                    indicator_name=row.indicator_name,
                    value=f"{row.measure_value} {row.unit or ''}".strip(),
                    source_reference=(f"{row.source_dataset_id} / FIPS "
                                      f"{row.county_fips} / {row.observation_year}"))
        flash("Regional research context recorded on the quote for audit. "
              "It is not a rating input.", "success")
    except DomainError as exc:
        flash(str(exc), "error")
    return redirect(url_for("quotes.quote_detail", quote_id=quote_id))


@bp.route("/<int:quote_id>/issue", methods=["POST"])
def issue(quote_id: int):
    actor = request.form.get("actor", "")
    try:
        with session_scope() as session:
            contract = policy_service.issue_policy(session, quote_id, actor=actor)
            contract_id = contract.contract_id
            contract_number = contract.contract_number
    except DomainError as exc:
        flash(str(exc), "error")
        return redirect(url_for("quotes.quote_detail", quote_id=quote_id))

    flash(f"Policy {contract_number} issued.", "success")
    return redirect(url_for("policies.policy_detail", contract_id=contract_id))
