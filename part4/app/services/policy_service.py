"""Policy issuance: converting an accepted quote into a CONTRACT.

This is the transactional core of the application. Issuing a policy writes
six things:

    CONTRACT            the policy header
    CONTRACT_BENEFIT    one row per quote coverage
    CONTRACT_PREMIUM    one row per benefit, year 1
    QUOTE_CONVERSION    the quote-to-contract bridge
    QUOTE               status moved to Converted
    QUOTE_STATUS_HISTORY the transition record

Either all six land or none do. A contract with no premium rows, or a
converted quote with no contract, is worse than a failed conversion: the
first under-bills silently and the second loses the sale.

Duplicate issuance is blocked three ways, deliberately layered:
  1. the service re-reads the quote with SELECT ... FOR UPDATE,
  2. it checks for an existing QUOTE_CONVERSION row,
  3. UNIQUE(QuoteID) on QUOTE_CONVERSION rejects anything that slips past
     the first two under concurrency.
"""

from __future__ import annotations

import logging
import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..models import (
    Contract,
    ContractBenefit,
    ContractPremium,
    Quote,
    QuoteConversion,
    QuoteStatusHistory,
)
from .errors import ConversionError, NotFound, ValidationError

log = logging.getLogger("part4.policy")


def _next_contract_number() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"POL-{stamp}-{secrets.token_hex(3).upper()}"


def get_contract(session: Session, contract_id: int) -> Contract:
    contract = session.scalars(
        select(Contract)
        .where(Contract.contract_id == contract_id)
        .options(
            selectinload(Contract.account),
            selectinload(Contract.benefits).selectinload(ContractBenefit.premiums),
            selectinload(Contract.conversion).selectinload(QuoteConversion.quote),
        )
    ).unique().one_or_none()
    if contract is None:
        raise NotFound(f"Contract {contract_id} does not exist.")
    return contract


def list_contracts(session: Session, limit: int = 25) -> list[Contract]:
    """Recent issued policies, most recent first."""
    return list(session.scalars(
        select(Contract)
        .options(selectinload(Contract.account))
        .order_by(Contract.contract_id.desc())
        .limit(limit)
    ))


def issue_policy(session: Session, quote_id: int, *, actor: str) -> Contract:
    """Convert an accepted quote into an issued CONTRACT.

    Caller supplies the session and owns the commit. Any exception raised
    here leaves the caller's session_scope to roll the whole thing back.
    """
    if not actor or not actor.strip():
        raise ValidationError("A named actor is required to issue a policy.")

    # 1. Lock the quote. Nothing else may change its state while the
    #    conversion runs.
    quote = session.scalars(
        select(Quote)
        .where(Quote.quote_id == quote_id)
        .with_for_update()
    ).one_or_none()
    if quote is None:
        raise NotFound(f"Quote {quote_id} does not exist.")

    # 2. Validate preconditions.
    if quote.quote_status == "Converted":
        raise ConversionError(
            f"Quote {quote.quote_number} has already been converted to a policy.")
    if quote.quote_status != "Accepted":
        raise ConversionError(
            f"Only an accepted quote can be issued. Quote {quote.quote_number} "
            f"is {quote.quote_status}.")
    if quote.account_id is None:
        raise ConversionError(
            "A quote must be tied to an account before a policy can be issued.")

    existing = session.scalars(
        select(QuoteConversion).where(QuoteConversion.quote_id == quote_id)
    ).one_or_none()
    if existing is not None:
        raise ConversionError(
            f"Quote {quote.quote_number} already produced contract "
            f"{existing.contract_id}.")

    coverages = list(session.scalars(
        select(Quote).where(Quote.quote_id == quote_id)
        .options(selectinload(Quote.coverages))).one().coverages)
    if not coverages:
        raise ConversionError("A quote with no coverage cannot become a policy.")

    effective = quote.effective_date or date.today()
    end = quote.expiration_date or (effective + timedelta(days=365))

    # 3. CONTRACT
    contract = Contract(
        contract_number=_next_contract_number(),
        account_id=quote.account_id,
        line_of_business=quote.product_line,
        plan_name=f"{quote.product_line} plan from {quote.quote_number}",
        status="Active",
        effective_date=effective,
        end_date=end,
    )
    session.add(contract)
    session.flush()

    # 4 & 5. CONTRACT_BENEFIT and CONTRACT_PREMIUM, one pair per coverage.
    for coverage in coverages:
        benefit = ContractBenefit(
            contract_id=contract.contract_id,
            benefit_name=coverage.coverage_name[:100],
            benefit_type=quote.product_line[:30],
            effective_date=effective,
            end_date=end,
        )
        session.add(benefit)
        session.flush()

        session.add(ContractPremium(
            benefit_id=benefit.benefit_id,
            # The issued premium is the premium proposed on the quote.
            # Conversion does not re-price.
            annualized_premium=Decimal(coverage.proposed_premium or 0),
            year_number=1,
            effective_date=effective,
            end_date=end,
        ))
        # Back-reference the quote coverage to the benefit it became, so
        # the issued policy can be traced line by line to the quote.
        coverage.benefit_id = benefit.benefit_id

    # 6. QUOTE_CONVERSION. UNIQUE(QuoteID) is the last line of defence.
    session.add(QuoteConversion(
        quote_id=quote_id,
        contract_id=contract.contract_id,
        converted_at=datetime.now(timezone.utc),
        conversion_status="Completed",
    ))

    # 7 & 8. Quote status and history.
    previous = quote.quote_status
    quote.quote_status = "Converted"
    quote.updated_at = datetime.now(timezone.utc)
    session.add(QuoteStatusHistory(
        quote_id=quote_id,
        previous_status=previous,
        new_status="Converted",
        changed_by=actor.strip(),
        reason=f"Issued contract {contract.contract_number}",
    ))

    try:
        session.flush()
    except IntegrityError as exc:
        # Reached when a concurrent transaction won the race. The caller's
        # session_scope rolls everything back; the message stays business
        # readable rather than exposing the constraint name.
        log.warning("Conversion integrity failure on quote %s: %s", quote_id, exc)
        raise ConversionError(
            "This quote was converted by another session. No second policy "
            "was created.") from exc

    log.info("Issued contract %s from quote %s (%d coverages)",
             contract.contract_number, quote.quote_number, len(coverages))
    return contract
