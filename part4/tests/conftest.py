"""Shared fixtures.

Test data is appended, never destructive. Each test creates its own quote
with a unique number and leaves the Part II and Part III rows alone, so the
suite can run repeatedly against the same database without a rebuild.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from part4.app.db import check_connection, read_session, session_scope  # noqa: E402
from part4.app.models import Account, Customer  # noqa: E402
from part4.app.services import quote_service, regional_context_service  # noqa: E402

ACTOR = "pytest.runner"


@pytest.fixture(scope="session", autouse=True)
def database_available() -> None:
    ok, message = check_connection()
    if not ok:
        pytest.skip(f"PostgreSQL is not available: {message}", allow_module_level=True)


@pytest.fixture(scope="session")
def ids() -> dict:
    """A customer and an account that has a regional profile."""
    with read_session() as session:
        customer_id = session.scalars(
            select(Customer.customer_id).order_by(Customer.customer_id)).first()
        profiles = regional_context_service.accounts_with_context(session, limit=1)
        account_id = (profiles[0]["account_id"] if profiles
                      else session.scalars(select(Account.account_id)).first())
    return {"customer_id": customer_id, "account_id": account_id}


@pytest.fixture
def draft_quote(ids) -> int:
    """A draft quote with no coverage."""
    today = date.today()
    with session_scope() as session:
        quote = quote_service.create_quote(
            session, customer_id=ids["customer_id"], account_id=ids["account_id"],
            product_line="Medical", requested_date=today, effective_date=today,
            expiration_date=today + timedelta(days=365), actor=ACTOR)
        return quote.quote_id


@pytest.fixture
def covered_quote(draft_quote) -> int:
    """A draft quote with one coverage line."""
    with session_scope() as session:
        quote_service.add_coverage(
            session, draft_quote, coverage_name="Test coverage",
            coverage_limit=Decimal("250000"), deductible=Decimal("1000"))
    return draft_quote


@pytest.fixture
def accepted_quote(covered_quote) -> int:
    """A quote carried all the way to Accepted, with payment authorized."""
    with session_scope() as session:
        quote_service.transition(session, covered_quote, "Submitted", actor=ACTOR)
        quote_service.transition(session, covered_quote, "Rated", actor=ACTOR)
        quote_service.transition(session, covered_quote, "Presented", actor=ACTOR)
        quote = quote_service.get_quote(session, covered_quote, eager=False)
        quote_service.authorize_payment(
            session, covered_quote, method="Card",
            amount=quote.estimated_premium or Decimal("0"), actor=ACTOR)
        quote_service.transition(session, covered_quote, "Accepted", actor=ACTOR)
    return covered_quote
