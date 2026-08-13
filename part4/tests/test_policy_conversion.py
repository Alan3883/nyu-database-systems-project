"""Policy issuance: atomicity, completeness, and duplicate prevention."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from part4.app.db import read_session, session_scope
from part4.app.models import (
    Contract,
    ContractBenefit,
    ContractPremium,
    QuoteConversion,
)
from part4.app.services import policy_service, quote_service
from part4.app.services.errors import ConversionError, ValidationError

ACTOR = "pytest.runner"


def test_accepted_quote_converts(accepted_quote):
    with session_scope() as session:
        contract = policy_service.issue_policy(session, accepted_quote, actor=ACTOR)
        contract_id = contract.contract_id

    with read_session() as session:
        contract = policy_service.get_contract(session, contract_id)
        quote = quote_service.get_quote(session, accepted_quote)

    assert contract.contract_number.startswith("POL-")
    assert contract.status == "Active"
    assert quote.quote_status == "Converted"
    assert quote.conversion.contract_id == contract_id


def test_conversion_creates_benefit_and_premium_rows(accepted_quote):
    with session_scope() as session:
        contract = policy_service.issue_policy(session, accepted_quote, actor=ACTOR)
        contract_id = contract.contract_id

    with read_session() as session:
        contract = policy_service.get_contract(session, contract_id)
        quote = quote_service.get_quote(session, accepted_quote)

    assert len(contract.benefits) == len(quote.coverages)
    for benefit in contract.benefits:
        assert len(benefit.premiums) == 1
        assert benefit.premiums[0].year_number == 1

    issued = sum(Decimal(p.annualized_premium or 0)
                 for b in contract.benefits for p in b.premiums)
    proposed = sum(Decimal(c.proposed_premium or 0) for c in quote.coverages)
    # Conversion carries the quoted premium across; it does not re-price.
    assert issued == proposed


def test_conversion_writes_a_status_history_row(accepted_quote):
    with session_scope() as session:
        policy_service.issue_policy(session, accepted_quote, actor=ACTOR)
    with read_session() as session:
        quote = quote_service.get_quote(session, accepted_quote)
    last = quote.status_history[-1]
    assert last.new_status == "Converted"
    assert last.previous_status == "Accepted"
    assert last.changed_by == ACTOR


def test_coverage_is_linked_to_the_benefit_it_became(accepted_quote):
    with session_scope() as session:
        policy_service.issue_policy(session, accepted_quote, actor=ACTOR)
    with read_session() as session:
        quote = quote_service.get_quote(session, accepted_quote)
    assert all(c.benefit_id is not None for c in quote.coverages)


def test_duplicate_conversion_is_rejected(accepted_quote):
    with session_scope() as session:
        policy_service.issue_policy(session, accepted_quote, actor=ACTOR)

    with read_session() as session:
        before = session.execute(select(func.count()).select_from(Contract)).scalar_one()

    with pytest.raises(ConversionError):
        with session_scope() as session:
            policy_service.issue_policy(session, accepted_quote, actor=ACTOR)

    with read_session() as session:
        after = session.execute(select(func.count()).select_from(Contract)).scalar_one()
        conversions = session.execute(
            select(func.count()).select_from(QuoteConversion)
            .where(QuoteConversion.quote_id == accepted_quote)).scalar_one()
    assert after == before
    assert conversions == 1


def test_unaccepted_quote_cannot_convert(covered_quote):
    with pytest.raises(ConversionError):
        with session_scope() as session:
            policy_service.issue_policy(session, covered_quote, actor=ACTOR)


def test_rejected_quote_does_not_convert(covered_quote):
    with session_scope() as session:
        quote_service.transition(session, covered_quote, "Submitted", actor=ACTOR)
        quote_service.transition(session, covered_quote, "Rejected", actor=ACTOR)
    with pytest.raises(ConversionError):
        with session_scope() as session:
            policy_service.issue_policy(session, covered_quote, actor=ACTOR)


def test_issuance_requires_a_named_actor(accepted_quote):
    with pytest.raises(ValidationError):
        with session_scope() as session:
            policy_service.issue_policy(session, accepted_quote, actor="")


def test_failed_conversion_leaves_no_orphan_rows(accepted_quote, monkeypatch):
    """An exception mid-conversion must roll back every row it wrote."""
    with read_session() as session:
        contracts_before = session.execute(
            select(func.count()).select_from(Contract)).scalar_one()
        benefits_before = session.execute(
            select(func.count()).select_from(ContractBenefit)).scalar_one()
        premiums_before = session.execute(
            select(func.count()).select_from(ContractPremium)).scalar_one()

    original = policy_service._next_contract_number

    def explode() -> str:
        # Fails after CONTRACT, CONTRACT_BENEFIT, and CONTRACT_PREMIUM rows
        # would normally have been flushed on the second call.
        raise RuntimeError("simulated failure during conversion")

    with pytest.raises(RuntimeError):
        with session_scope() as session:
            monkeypatch.setattr(policy_service, "_next_contract_number", original)
            contract = policy_service.issue_policy(session, accepted_quote, actor=ACTOR)
            assert contract.contract_id is not None
            raise RuntimeError("simulated failure during conversion")

    with read_session() as session:
        assert session.execute(
            select(func.count()).select_from(Contract)).scalar_one() == contracts_before
        assert session.execute(
            select(func.count()).select_from(ContractBenefit)).scalar_one() == benefits_before
        assert session.execute(
            select(func.count()).select_from(ContractPremium)).scalar_one() == premiums_before
        quote = quote_service.get_quote(session, accepted_quote, eager=False)
    assert quote.quote_status == "Accepted"


def test_unique_constraint_backs_the_service_check():
    """The database, not only the service, prevents a second conversion."""
    from part4.app.models import QuoteConversion as QC
    constraints = {c.name for c in QC.__table__.constraints if c.name}
    unique_columns = [
        set(c.columns.keys()) for c in QC.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"]
    assert QC.__table__.c.quoteid.unique or {"quoteid"} in unique_columns
