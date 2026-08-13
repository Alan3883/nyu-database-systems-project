"""Quote workflow: creation, coverage, state transitions, payment.

Transaction rule for this module: a quote and its first status-history row
are written in one transaction, and every later state change writes the
quote row and its history row in one transaction. A quote whose recorded
state does not match its history would make the audit trail useless, so the
two writes are never allowed to succeed separately.
"""

from __future__ import annotations

import logging
import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..config import CONFIG
from ..models import (
    Account,
    Customer,
    PaymentAuthorization,
    Quote,
    QuoteCoverage,
    QuoteRiskFactor,
    QuoteStatusHistory,
)
from .errors import InvalidTransition, NotFound, ValidationError

log = logging.getLogger("part4.quote")

# Legal state transitions. The database constrains the set of states;
# this table constrains the moves between them.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "Draft":     {"Submitted", "Expired"},
    "Submitted": {"Rated", "Rejected", "Expired"},
    "Rated":     {"Presented", "Rejected", "Expired"},
    "Presented": {"Accepted", "Rejected", "Expired"},
    "Accepted":  {"Converted", "Expired"},
    "Rejected":  set(),
    "Expired":   set(),
    "Converted": set(),
}

OPEN_STATUSES = ("Draft", "Submitted", "Rated", "Presented")
PRODUCT_LINES = ("Medical", "Dental", "Vision", "Life", "Disability")


# ---------------------------------------------------------------------
# Demonstration pricing
# ---------------------------------------------------------------------
def demonstration_premium(coverage_limit: Decimal | None,
                          deductible: Decimal | None) -> Decimal:
    """Compute a proposed premium for a coverage line.

    DEMONSTRATION RULE, NOT AN INSURANCE RATE. The project has no rating
    engine and no filed rates. The formula uses only two values the user
    typed on the coverage form:

        premium = limit/1000 * rate  -  deductible * credit

    Nothing else is an input. In particular no regional health value, no
    ML cluster, and no customer attribute reaches this function. That is
    the mechanical guarantee behind the governance claim that model output
    does not affect price: the pricing code cannot see it.
    """
    limit = Decimal(coverage_limit or 0)
    excess = Decimal(deductible or 0)
    gross = (limit / Decimal(1000)) * Decimal(str(CONFIG.demo_rate_per_1000_limit))
    credit = excess * Decimal(str(CONFIG.demo_deductible_credit))
    premium = gross - credit
    if premium < 0:
        premium = Decimal(0)
    return premium.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _next_quote_number(session: Session) -> str:
    """Build a unique, human-readable quote number.

    The random suffix keeps repeated demonstration runs from colliding on
    uq_quote_number without needing a dedicated sequence.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"Q4-{stamp}-{secrets.token_hex(3).upper()}"


# ---------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------
def dashboard_counts(session: Session) -> dict[str, int]:
    """Quote counts by status in one grouped query, not one query per status."""
    rows = session.execute(
        select(Quote.quote_status, func.count())
        .group_by(Quote.quote_status)
    ).all()
    counts = {status: count for status, count in rows}
    counts["Open"] = sum(counts.get(s, 0) for s in OPEN_STATUSES)
    counts["Total"] = sum(c for s, c in counts.items() if s != "Open" and s != "Total")
    return counts


def list_quotes(session: Session, status: str | None = None,
                limit: int | None = None) -> list[Quote]:
    """List quotes, newest first, with the customer eagerly loaded.

    selectinload on customer is the fix for the N+1 the list page would
    otherwise produce: the template prints a customer name per row, and
    with lazy loading that is one extra SELECT per quote. Measurements are
    in part4/evidence/query_performance.csv.
    """
    stmt = (
        select(Quote)
        .options(selectinload(Quote.customer))
        .order_by(Quote.created_at.desc(), Quote.quote_id.desc())
    )
    if status:
        stmt = stmt.where(Quote.quote_status == status)
    stmt = stmt.limit(limit or CONFIG.page_size)
    return list(session.scalars(stmt))


def get_quote(session: Session, quote_id: int, *, eager: bool = True) -> Quote:
    """Load one quote for the detail page.

    With eager=True the whole aggregate arrives in a bounded number of
    statements. With eager=False the relationships lazy-load, which is the
    'before' case in the optimization measurement.
    """
    stmt = select(Quote).where(Quote.quote_id == quote_id)
    if eager:
        stmt = stmt.options(
            selectinload(Quote.customer),
            selectinload(Quote.account),
            selectinload(Quote.coverages),
            selectinload(Quote.status_history),
            selectinload(Quote.risk_factors),
            selectinload(Quote.payment_authorizations),
            selectinload(Quote.conversion),
        )
    quote = session.scalars(stmt).unique().one_or_none()
    if quote is None:
        raise NotFound(f"Quote {quote_id} does not exist.")
    return quote


def find_quote_by_number(session: Session, quote_number: str) -> Quote | None:
    return session.scalars(
        select(Quote).where(Quote.quote_number == quote_number)).one_or_none()


def list_customers(session: Session, limit: int = 200) -> list[Customer]:
    return list(session.scalars(
        select(Customer).order_by(Customer.last_name, Customer.first_name).limit(limit)))


def list_accounts(session: Session, limit: int = 200) -> list[Account]:
    return list(session.scalars(
        select(Account).order_by(Account.account_name).limit(limit)))


# ---------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------
def create_quote(session: Session, *, customer_id: int, account_id: int | None,
                 product_line: str, requested_date: date,
                 effective_date: date | None, expiration_date: date | None,
                 actor: str, associate_id: int | None = None) -> Quote:
    """Create a draft quote and its opening history row.

    Caller owns the transaction. Both rows commit together or neither does.
    """
    if product_line not in PRODUCT_LINES:
        raise ValidationError(f"Unknown product line {product_line!r}.")
    if session.get(Customer, customer_id) is None:
        raise NotFound(f"Customer {customer_id} does not exist.")
    if account_id is not None and session.get(Account, account_id) is None:
        raise NotFound(f"Account {account_id} does not exist.")
    if effective_date and expiration_date and effective_date > expiration_date:
        raise ValidationError("Effective date must not be after the expiration date.")
    if expiration_date is None and effective_date is not None:
        expiration_date = effective_date + timedelta(days=365)

    quote = Quote(
        quote_number=_next_quote_number(session),
        customer_id=customer_id,
        account_id=account_id,
        associate_id=associate_id,
        product_line=product_line,
        quote_status="Draft",
        requested_date=requested_date,
        effective_date=effective_date,
        expiration_date=expiration_date,
        estimated_premium=Decimal("0.00"),
    )
    session.add(quote)
    session.flush()  # assign quoteid so the history row can reference it

    session.add(QuoteStatusHistory(
        quote_id=quote.quote_id,
        previous_status=None,
        new_status="Draft",
        changed_by=actor,
        reason="Quote created",
    ))
    log.info("Created quote %s for customer %s", quote.quote_number, customer_id)
    return quote


def add_coverage(session: Session, quote_id: int, *, coverage_name: str,
                 coverage_limit: Decimal | None, deductible: Decimal | None,
                 proposed_premium: Decimal | None = None) -> QuoteCoverage:
    """Add a coverage line and refresh the quote's estimated premium."""
    quote = get_quote(session, quote_id, eager=False)
    if quote.quote_status in ("Converted", "Rejected", "Expired"):
        raise ValidationError(
            f"Coverage cannot be added to a {quote.quote_status.lower()} quote.")
    if not coverage_name.strip():
        raise ValidationError("Coverage name is required.")
    if coverage_limit is not None and coverage_limit < 0:
        raise ValidationError("Coverage limit cannot be negative.")
    if deductible is not None and deductible < 0:
        raise ValidationError("Deductible cannot be negative.")

    premium = (proposed_premium if proposed_premium is not None
               else demonstration_premium(coverage_limit, deductible))
    coverage = QuoteCoverage(
        quote_id=quote_id,
        coverage_name=coverage_name.strip(),
        coverage_limit=coverage_limit,
        deductible=deductible,
        proposed_premium=premium,
    )
    session.add(coverage)
    session.flush()
    recalculate_estimated_premium(session, quote_id)
    return coverage


def recalculate_estimated_premium(session: Session, quote_id: int) -> Decimal:
    """Sum the coverage lines into QUOTE.EstimatedPremium.

    Aggregated in the database rather than by loading every coverage row
    into Python. The estimate is a sum of user-entered coverage premiums
    and nothing else.
    """
    total = session.execute(
        select(func.coalesce(func.sum(QuoteCoverage.proposed_premium), 0))
        .where(QuoteCoverage.quote_id == quote_id)
    ).scalar_one()
    quote = session.get(Quote, quote_id)
    quote.estimated_premium = Decimal(total).quantize(Decimal("0.01"))
    return quote.estimated_premium


def transition(session: Session, quote_id: int, new_status: str, *,
               actor: str, reason: str | None = None) -> Quote:
    """Move a quote to a new state and record the move.

    The quote row is locked for the duration so two concurrent requests
    cannot both read 'Presented' and both write 'Accepted'.
    """
    if not actor or not actor.strip():
        raise ValidationError("A named actor is required for a status change.")

    quote = session.scalars(
        select(Quote).where(Quote.quote_id == quote_id).with_for_update()
    ).one_or_none()
    if quote is None:
        raise NotFound(f"Quote {quote_id} does not exist.")

    current = quote.quote_status
    if new_status == current:
        raise InvalidTransition(f"Quote is already {current}.")
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if new_status not in allowed:
        raise InvalidTransition(
            f"Cannot move a {current} quote to {new_status}. "
            f"Allowed from {current}: {', '.join(sorted(allowed)) or 'none'}.")

    if new_status in ("Submitted", "Accepted") and not quote.coverages:
        raise ValidationError("A quote needs at least one coverage line first.")
    if new_status == "Accepted":
        authorized = session.scalars(
            select(PaymentAuthorization).where(
                PaymentAuthorization.quote_id == quote_id,
                PaymentAuthorization.authorization_status == "Authorized")
        ).first()
        if authorized is None:
            raise ValidationError(
                "Payment must be authorized before a quote can be accepted.")

    quote.quote_status = new_status
    quote.updated_at = datetime.now(timezone.utc)
    session.add(QuoteStatusHistory(
        quote_id=quote_id,
        previous_status=current,
        new_status=new_status,
        changed_by=actor.strip(),
        reason=reason,
    ))
    log.info("Quote %s %s -> %s by %s", quote.quote_number, current, new_status, actor)
    return quote


def authorize_payment(session: Session, quote_id: int, *, method: str,
                      amount: Decimal, actor: str) -> PaymentAuthorization:
    """Record a payment authorisation reference.

    No cardholder data is accepted or stored. The reference stands in for
    what a gateway would return; the application never sees an instrument.
    """
    quote = get_quote(session, quote_id, eager=False)
    if quote.quote_status not in ("Rated", "Presented"):
        raise ValidationError(
            "Payment can be authorized once the quote has been presented.")
    if method not in ("Card", "ACH", "Invoice", "Payroll"):
        raise ValidationError(f"Unsupported payment method {method!r}.")
    if amount is None or amount < 0:
        raise ValidationError("Authorized amount must be zero or greater.")

    auth = PaymentAuthorization(
        quote_id=quote_id,
        authorization_reference=f"AUTH-{secrets.token_hex(6).upper()}",
        payment_method_type=method,
        authorized_amount=Decimal(amount).quantize(Decimal("0.01")),
        authorization_status="Authorized",
        authorized_at=datetime.now(timezone.utc),
    )
    session.add(auth)
    session.flush()
    log.info("Authorized %s on quote %s by %s", auth.authorization_reference,
             quote.quote_number, actor)
    return auth


def record_regional_research_factor(session: Session, quote_id: int, *,
                                    indicator_name: str, value: str,
                                    source_reference: str) -> QuoteRiskFactor:
    """Log that regional context was viewed against a quote.

    SourceType is fixed to 'RegionalAggregate' and ReviewStatus to
    'Pending'. The row is an audit record of what an underwriter saw. It
    is never read by pricing or by any eligibility decision.
    """
    factor = QuoteRiskFactor(
        quote_id=quote_id,
        risk_factor_type="RegionalResearchContext",
        source_type="RegionalAggregate",
        source_reference=source_reference[:200],
        factor_value=f"{indicator_name}: {value}"[:200],
        review_status="Pending",
    )
    session.add(factor)
    session.flush()
    return factor
