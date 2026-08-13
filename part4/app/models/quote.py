"""Mappings for the six Part III quote-workflow tables.

The workflow they support is:

    Draft -> Submitted -> Rated -> Presented -> Accepted -> Converted
                                             \\-> Rejected
                                             \\-> Expired

The state set is enforced by ck_quote_status in the database. The legal
transitions between those states are enforced by the service layer, in
quote_service.ALLOWED_TRANSITIONS, and every transition writes a
QUOTE_STATUS_HISTORY row in the same transaction.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.schema import FetchedValue
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class Quote(Base):
    __tablename__ = "quote"

    quote_id: Mapped[int] = mapped_column("quoteid", BigInteger, primary_key=True)
    quote_number: Mapped[str] = mapped_column("quotenumber", String(50))
    customer_id: Mapped[int] = mapped_column(
        "customerid", Integer, ForeignKey("customer.customerid"))
    account_id: Mapped[int | None] = mapped_column(
        "accountid", Integer, ForeignKey("account.accountid"))
    associate_id: Mapped[int | None] = mapped_column(
        "associateid", Integer, ForeignKey("associate.associateid"))
    product_line: Mapped[str] = mapped_column("productline", String(20))
    quote_status: Mapped[str] = mapped_column("quotestatus", String(20))
    requested_date: Mapped[date] = mapped_column("requesteddate", Date)
    effective_date: Mapped[date | None] = mapped_column("effectivedate", Date)
    expiration_date: Mapped[date | None] = mapped_column("expirationdate", Date)
    estimated_premium: Mapped[Decimal | None] = mapped_column(
        "estimatedpremium", Numeric(14, 2))
    created_at: Mapped[datetime | None] = mapped_column("createdat", DateTime(timezone=True), server_default=FetchedValue())
    updated_at: Mapped[datetime | None] = mapped_column("updatedat", DateTime(timezone=True), server_default=FetchedValue())

    customer: Mapped["Customer"] = relationship(back_populates="quotes")  # noqa: F821
    account: Mapped["Account | None"] = relationship()  # noqa: F821
    associate: Mapped["Associate | None"] = relationship()  # noqa: F821
    coverages: Mapped[list["QuoteCoverage"]] = relationship(
        back_populates="quote", cascade="all, delete-orphan",
        order_by="QuoteCoverage.quote_coverage_id")
    risk_factors: Mapped[list["QuoteRiskFactor"]] = relationship(
        back_populates="quote", cascade="all, delete-orphan")
    status_history: Mapped[list["QuoteStatusHistory"]] = relationship(
        back_populates="quote", cascade="all, delete-orphan",
        order_by="QuoteStatusHistory.changed_at")
    payment_authorizations: Mapped[list["PaymentAuthorization"]] = relationship(
        back_populates="quote", cascade="all, delete-orphan")
    conversion: Mapped["QuoteConversion | None"] = relationship(back_populates="quote")

    @property
    def is_open(self) -> bool:
        return self.quote_status in ("Draft", "Submitted", "Rated", "Presented")

    @property
    def authorized_payment(self) -> "PaymentAuthorization | None":
        for auth in self.payment_authorizations:
            if auth.authorization_status == "Authorized":
                return auth
        return None


class QuoteCoverage(Base):
    __tablename__ = "quote_coverage"

    quote_coverage_id: Mapped[int] = mapped_column(
        "quotecoverageid", BigInteger, primary_key=True)
    quote_id: Mapped[int] = mapped_column(
        "quoteid", BigInteger, ForeignKey("quote.quoteid", ondelete="CASCADE"))
    benefit_id: Mapped[int | None] = mapped_column(
        "benefitid", Integer, ForeignKey("contract_benefit.benefitid"))
    coverage_name: Mapped[str] = mapped_column("coveragename", String(100))
    coverage_limit: Mapped[Decimal | None] = mapped_column("coveragelimit", Numeric(14, 2))
    deductible: Mapped[Decimal | None] = mapped_column("deductible", Numeric(14, 2))
    proposed_premium: Mapped[Decimal | None] = mapped_column(
        "proposedpremium", Numeric(14, 2))
    created_at: Mapped[datetime | None] = mapped_column("createdat", DateTime(timezone=True), server_default=FetchedValue())

    quote: Mapped["Quote"] = relationship(back_populates="coverages")


class QuoteRiskFactor(Base):
    """A factor considered on a quote.

    source_type is the audit control. 'RegionalAggregate' rows reference a
    geographic area, never a person, and they are recorded for traceability
    only: nothing in the rating path reads this table.
    """

    __tablename__ = "quote_risk_factor"

    quote_risk_factor_id: Mapped[int] = mapped_column(
        "quoteriskfactorid", BigInteger, primary_key=True)
    quote_id: Mapped[int] = mapped_column(
        "quoteid", BigInteger, ForeignKey("quote.quoteid", ondelete="CASCADE"))
    risk_factor_type: Mapped[str] = mapped_column("riskfactortype", String(50))
    source_type: Mapped[str] = mapped_column("sourcetype", String(30))
    source_reference: Mapped[str | None] = mapped_column("sourcereference", String(200))
    factor_value: Mapped[str | None] = mapped_column("factorvalue", String(200))
    review_status: Mapped[str] = mapped_column("reviewstatus", String(20))
    created_at: Mapped[datetime | None] = mapped_column("createdat", DateTime(timezone=True), server_default=FetchedValue())

    quote: Mapped["Quote"] = relationship(back_populates="risk_factors")


class QuoteStatusHistory(Base):
    __tablename__ = "quote_status_history"

    quote_status_history_id: Mapped[int] = mapped_column(
        "quotestatushistoryid", BigInteger, primary_key=True)
    quote_id: Mapped[int] = mapped_column(
        "quoteid", BigInteger, ForeignKey("quote.quoteid", ondelete="CASCADE"))
    previous_status: Mapped[str | None] = mapped_column("previousstatus", String(20))
    new_status: Mapped[str] = mapped_column("newstatus", String(20))
    changed_at: Mapped[datetime | None] = mapped_column("changedat", DateTime(timezone=True), server_default=FetchedValue())
    changed_by: Mapped[str] = mapped_column("changedby", String(100))
    reason: Mapped[str | None] = mapped_column("reason", String(300))

    quote: Mapped["Quote"] = relationship(back_populates="status_history")


class PaymentAuthorization(Base):
    """Authorisation reference only.

    No card number, bank account, or cardholder name is stored or mapped.
    The database is deliberately kept out of PCI scope.
    """

    __tablename__ = "payment_authorization"

    payment_authorization_id: Mapped[int] = mapped_column(
        "paymentauthorizationid", BigInteger, primary_key=True)
    quote_id: Mapped[int] = mapped_column(
        "quoteid", BigInteger, ForeignKey("quote.quoteid", ondelete="CASCADE"))
    authorization_reference: Mapped[str] = mapped_column(
        "authorizationreference", String(100))
    payment_method_type: Mapped[str] = mapped_column("paymentmethodtype", String(30))
    authorized_amount: Mapped[Decimal] = mapped_column("authorizedamount", Numeric(14, 2))
    authorization_status: Mapped[str] = mapped_column("authorizationstatus", String(20))
    authorized_at: Mapped[datetime | None] = mapped_column(
        "authorizedat", DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column("createdat", DateTime(timezone=True), server_default=FetchedValue())

    quote: Mapped["Quote"] = relationship(back_populates="payment_authorizations")


class QuoteConversion(Base):
    """The quote-to-contract bridge.

    UNIQUE(QuoteID) in the database is the hard guarantee that one quote
    cannot produce two policies. The service layer also checks and takes a
    row lock, but the constraint is what holds under concurrency.
    """

    __tablename__ = "quote_conversion"

    quote_conversion_id: Mapped[int] = mapped_column(
        "quoteconversionid", BigInteger, primary_key=True)
    quote_id: Mapped[int] = mapped_column(
        "quoteid", BigInteger, ForeignKey("quote.quoteid"), unique=True)
    contract_id: Mapped[int] = mapped_column(
        "contractid", Integer, ForeignKey("contract.contractid"))
    converted_at: Mapped[datetime | None] = mapped_column(
        "convertedat", DateTime(timezone=True), server_default=FetchedValue())
    conversion_status: Mapped[str] = mapped_column("conversionstatus", String(20))

    quote: Mapped["Quote"] = relationship(back_populates="conversion")
    contract: Mapped["Contract"] = relationship(back_populates="conversion")  # noqa: F821
