"""Quote creation, coverage, state transitions, and payment authorisation."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from part4.app.db import read_session, session_scope
from part4.app.models import Quote, QuoteStatusHistory
from part4.app.services import quote_service
from part4.app.services.errors import InvalidTransition, NotFound, ValidationError

ACTOR = "pytest.runner"


def test_create_quote_starts_as_draft(draft_quote):
    with read_session() as session:
        quote = quote_service.get_quote(session, draft_quote)
    assert quote.quote_status == "Draft"
    assert quote.quote_number.startswith("Q4-")
    assert quote.estimated_premium == Decimal("0.00")


def test_unknown_customer_is_rejected(ids):
    with pytest.raises(NotFound):
        with session_scope() as session:
            quote_service.create_quote(
                session, customer_id=987654321, account_id=ids["account_id"],
                product_line="Medical", requested_date=date.today(),
                effective_date=None, expiration_date=None, actor=ACTOR)


def test_unknown_product_line_is_rejected(ids):
    with pytest.raises(ValidationError):
        with session_scope() as session:
            quote_service.create_quote(
                session, customer_id=ids["customer_id"],
                account_id=ids["account_id"], product_line="Spaceflight",
                requested_date=date.today(), effective_date=None,
                expiration_date=None, actor=ACTOR)


def test_invalid_dates_are_rejected(ids):
    today = date.today()
    with pytest.raises(ValidationError):
        with session_scope() as session:
            quote_service.create_quote(
                session, customer_id=ids["customer_id"],
                account_id=ids["account_id"], product_line="Medical",
                requested_date=today, effective_date=today,
                expiration_date=today - timedelta(days=1), actor=ACTOR)


def test_coverage_updates_the_estimate(draft_quote):
    with session_scope() as session:
        quote_service.add_coverage(
            session, draft_quote, coverage_name="Line A",
            coverage_limit=Decimal("100000"), deductible=Decimal("0"))
        quote_service.add_coverage(
            session, draft_quote, coverage_name="Line B",
            coverage_limit=Decimal("100000"), deductible=Decimal("0"))
    with read_session() as session:
        quote = quote_service.get_quote(session, draft_quote)
    expected = quote_service.demonstration_premium(Decimal("100000"), Decimal("0")) * 2
    assert quote.estimated_premium == expected
    assert len(quote.coverages) == 2


def test_demonstration_premium_uses_only_limit_and_deductible():
    high = quote_service.demonstration_premium(Decimal("500000"), Decimal("0"))
    low = quote_service.demonstration_premium(Decimal("500000"), Decimal("5000"))
    assert high > low
    assert quote_service.demonstration_premium(Decimal("0"), Decimal("99999")) == Decimal("0.00")


def test_submission_requires_coverage(draft_quote):
    with pytest.raises(ValidationError):
        with session_scope() as session:
            quote_service.transition(session, draft_quote, "Submitted", actor=ACTOR)


def test_valid_transition_sequence(covered_quote):
    with session_scope() as session:
        quote_service.transition(session, covered_quote, "Submitted", actor=ACTOR)
        quote_service.transition(session, covered_quote, "Rated", actor=ACTOR)
        quote_service.transition(session, covered_quote, "Presented", actor=ACTOR)
    with read_session() as session:
        quote = quote_service.get_quote(session, covered_quote)
        statuses = [h.new_status for h in quote.status_history]
    assert quote.quote_status == "Presented"
    assert statuses == ["Draft", "Submitted", "Rated", "Presented"]


def test_illegal_transition_is_refused(covered_quote):
    with session_scope() as session:
        quote_service.transition(session, covered_quote, "Submitted", actor=ACTOR)
    with pytest.raises(InvalidTransition):
        with session_scope() as session:
            quote_service.transition(session, covered_quote, "Converted", actor=ACTOR)
    with read_session() as session:
        quote = quote_service.get_quote(session, covered_quote, eager=False)
    assert quote.quote_status == "Submitted"


def test_transition_requires_a_named_actor(covered_quote):
    with pytest.raises(ValidationError):
        with session_scope() as session:
            quote_service.transition(session, covered_quote, "Submitted", actor="  ")


def test_acceptance_requires_authorized_payment(covered_quote):
    with session_scope() as session:
        quote_service.transition(session, covered_quote, "Submitted", actor=ACTOR)
        quote_service.transition(session, covered_quote, "Rated", actor=ACTOR)
        quote_service.transition(session, covered_quote, "Presented", actor=ACTOR)
    with pytest.raises(ValidationError):
        with session_scope() as session:
            quote_service.transition(session, covered_quote, "Accepted", actor=ACTOR)


def test_payment_stores_a_reference_only(accepted_quote):
    with read_session() as session:
        quote = quote_service.get_quote(session, accepted_quote)
        auth = quote.authorized_payment
    assert auth is not None
    assert auth.authorization_reference.startswith("AUTH-")
    assert auth.authorization_status == "Authorized"
    # The table has no column that could hold an instrument.
    columns = {c.name for c in auth.__table__.columns}
    assert not columns & {"cardnumber", "pan", "iban", "accountnumber", "cvv"}


def test_rejected_quote_is_terminal(covered_quote):
    with session_scope() as session:
        quote_service.transition(session, covered_quote, "Submitted", actor=ACTOR)
        quote_service.transition(session, covered_quote, "Rejected", actor=ACTOR,
                                 reason="Test rejection")
    assert quote_service.ALLOWED_TRANSITIONS["Rejected"] == set()
    with pytest.raises(InvalidTransition):
        with session_scope() as session:
            quote_service.transition(session, covered_quote, "Accepted", actor=ACTOR)


def test_quote_numbers_are_unique(ids):
    numbers = set()
    for _ in range(5):
        with session_scope() as session:
            quote = quote_service.create_quote(
                session, customer_id=ids["customer_id"],
                account_id=ids["account_id"], product_line="Vision",
                requested_date=date.today(), effective_date=None,
                expiration_date=None, actor=ACTOR)
            numbers.add(quote.quote_number)
    assert len(numbers) == 5


def test_status_filter_returns_only_that_status():
    with read_session() as session:
        drafts = quote_service.list_quotes(session, status="Draft", limit=20)
    assert all(q.quote_status == "Draft" for q in drafts)
