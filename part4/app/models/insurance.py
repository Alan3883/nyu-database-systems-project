"""Mappings for the Part II insurance core and the hybrid public-health path.

Two groups of tables live here:

  Insurance core   CUSTOMER, ACCOUNT, ASSOCIATE, CONTRACT, CONTRACT_BENEFIT,
                   CONTRACT_PREMIUM. CONTRACT is the issued policy; Part III
                   deliberately did not add a parallel POLICY table.

  Regional path    ACCOUNT_GEOGRAPHY -> GEOGRAPHIC_AREA -> HEALTH_OBSERVATION
                   -> HEALTH_INDICATOR, plus the materialized view that
                   pre-joins them. This path carries county-level aggregates
                   only. Nothing in it describes a person.

CONTRACT, CONTRACT_BENEFIT, and CONTRACT_PREMIUM take their keys from the
sequences added in part4/db/01_part4_extension.sql. Declaring the Sequence
on the mapping lets SQLAlchemy fetch the value with the INSERT rather than
issuing a separate round trip.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Sequence,
    String,
)
from sqlalchemy.schema import FetchedValue
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class Customer(Base):
    __tablename__ = "customer"

    customer_id: Mapped[int] = mapped_column("customerid", Integer, primary_key=True)
    last_name: Mapped[str | None] = mapped_column("custlastname", String(100))
    first_name: Mapped[str | None] = mapped_column("custfirstname", String(100))
    date_of_birth: Mapped[date | None] = mapped_column("custdob", Date)
    customer_type: Mapped[str] = mapped_column("customertype", String(20))
    status: Mapped[str] = mapped_column("status", String(20))
    created_at: Mapped[datetime] = mapped_column("createdat", DateTime(timezone=True), server_default=FetchedValue())
    updated_at: Mapped[datetime] = mapped_column("updatedat", DateTime(timezone=True), server_default=FetchedValue())

    # SSN_TIN exists in the table and is deliberately not mapped. The
    # application has no use for it, and an unmapped column cannot be
    # leaked by a template that renders an object generically.

    quotes: Mapped[list["Quote"]] = relationship(back_populates="customer")  # noqa: F821

    @property
    def display_name(self) -> str:
        parts = [p for p in (self.first_name, self.last_name) if p]
        return " ".join(parts) or f"Customer {self.customer_id}"


class Account(Base):
    __tablename__ = "account"

    account_id: Mapped[int] = mapped_column("accountid", Integer, primary_key=True)
    account_name: Mapped[str] = mapped_column("accountname", String(200))
    company_code: Mapped[str] = mapped_column("companycode", String(20))
    address1: Mapped[str | None] = mapped_column("address1", String(200))
    city: Mapped[str | None] = mapped_column("city", String(100))
    state: Mapped[str | None] = mapped_column("state", String(2))
    zip_code: Mapped[str | None] = mapped_column("zip", String(10))
    account_type: Mapped[str] = mapped_column("accounttype", String(30))
    status: Mapped[str] = mapped_column("status", String(20))
    start_date: Mapped[date | None] = mapped_column("startdate", Date)
    end_date: Mapped[date | None] = mapped_column("enddate", Date)

    geographies: Mapped[list["AccountGeography"]] = relationship(
        back_populates="account")
    contracts: Mapped[list["Contract"]] = relationship(back_populates="account")


class Associate(Base):
    __tablename__ = "associate"

    associate_id: Mapped[int] = mapped_column("associateid", Integer, primary_key=True)
    last_name: Mapped[str | None] = mapped_column("assoclastname", String(100))
    first_name: Mapped[str | None] = mapped_column("assocfirstname", String(100))
    status: Mapped[str | None] = mapped_column("status", String(20))


class GeographicArea(Base):
    __tablename__ = "geographic_area"

    geography_id: Mapped[int] = mapped_column("geographyid", Integer, primary_key=True)
    parent_geography_id: Mapped[int | None] = mapped_column(
        "parentgeographyid", Integer, ForeignKey("geographic_area.geographyid"))
    geography_type: Mapped[str] = mapped_column("geographytype", String(20))
    geography_name: Mapped[str] = mapped_column("geographyname", String(150))
    state_code: Mapped[str | None] = mapped_column("statecode", String(2))
    # County FIPS is the join key shared with every public source.
    county_fips: Mapped[str | None] = mapped_column("countyfips", String(5))
    zcta: Mapped[str | None] = mapped_column("zcta", String(5))
    country_code: Mapped[str | None] = mapped_column("countrycode", String(2))

    observations: Mapped[list["HealthObservation"]] = relationship(
        back_populates="geography")


class AccountGeography(Base):
    __tablename__ = "account_geography"

    account_id: Mapped[int] = mapped_column(
        "accountid", Integer, ForeignKey("account.accountid"), primary_key=True)
    geography_id: Mapped[int] = mapped_column(
        "geographyid", Integer, ForeignKey("geographic_area.geographyid"),
        primary_key=True)
    relationship_type: Mapped[str] = mapped_column(
        "relationshiptype", String(30), primary_key=True)
    start_date: Mapped[date | None] = mapped_column("startdate", Date)
    end_date: Mapped[date | None] = mapped_column("enddate", Date)

    account: Mapped["Account"] = relationship(back_populates="geographies")
    geography: Mapped["GeographicArea"] = relationship()


class HealthIndicator(Base):
    __tablename__ = "health_indicator"

    indicator_id: Mapped[int] = mapped_column("indicatorid", Integer, primary_key=True)
    indicator_code: Mapped[str] = mapped_column("indicatorcode", String(30))
    indicator_name: Mapped[str] = mapped_column("indicatorname", String(300))
    disease_category: Mapped[str | None] = mapped_column("diseasecategory", String(100))
    factor_category: Mapped[str | None] = mapped_column("factorcategory", String(100))
    unit: Mapped[str | None] = mapped_column("unit", String(30))
    description: Mapped[str | None] = mapped_column("description", String(500))


class HealthObservation(Base):
    __tablename__ = "health_observation"

    observation_id: Mapped[int] = mapped_column("observationid", Integer, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(
        "datasetid", String(10), ForeignKey("dataset.datasetid"))
    geography_id: Mapped[int] = mapped_column(
        "geographyid", Integer, ForeignKey("geographic_area.geographyid"))
    indicator_id: Mapped[int] = mapped_column(
        "indicatorid", Integer, ForeignKey("health_indicator.indicatorid"))
    observation_year: Mapped[int | None] = mapped_column("observationyear", Integer)
    population_group: Mapped[str | None] = mapped_column("populationgroup", String(50))
    measure_value: Mapped[Decimal | None] = mapped_column("measurevalue", Numeric(12, 4))
    lower_confidence_limit: Mapped[Decimal | None] = mapped_column(
        "lowerconfidencelimit", Numeric(12, 4))
    upper_confidence_limit: Mapped[Decimal | None] = mapped_column(
        "upperconfidencelimit", Numeric(12, 4))
    notes: Mapped[str | None] = mapped_column("notes", String(200))

    geography: Mapped["GeographicArea"] = relationship(back_populates="observations")
    indicator: Mapped["HealthIndicator"] = relationship()


class Contract(Base):
    """An issued policy.

    Part III decided against a separate POLICY table: CONTRACT already
    carries contract number, account, line of business, plan, status, and
    dates, and it owns the benefit and premium hierarchy.
    """

    __tablename__ = "contract"

    contract_id: Mapped[int] = mapped_column(
        "contractid", Integer, Sequence("contract_contractid_seq"), primary_key=True)
    contract_number: Mapped[str] = mapped_column("contractnumber", String(50))
    account_id: Mapped[int] = mapped_column(
        "accountid", Integer, ForeignKey("account.accountid"))
    line_of_business: Mapped[str | None] = mapped_column("lineofbusiness", String(30))
    plan_name: Mapped[str | None] = mapped_column("planname", String(100))
    status: Mapped[str] = mapped_column("status", String(20))
    effective_date: Mapped[date | None] = mapped_column("effectivedate", Date)
    end_date: Mapped[date | None] = mapped_column("enddate", Date)
    created_at: Mapped[datetime | None] = mapped_column("createdat", DateTime(timezone=True), server_default=FetchedValue())
    updated_at: Mapped[datetime | None] = mapped_column("updatedat", DateTime(timezone=True), server_default=FetchedValue())

    account: Mapped["Account"] = relationship(back_populates="contracts")
    benefits: Mapped[list["ContractBenefit"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan")
    conversion: Mapped["QuoteConversion | None"] = relationship(  # noqa: F821
        back_populates="contract")


class ContractBenefit(Base):
    __tablename__ = "contract_benefit"

    benefit_id: Mapped[int] = mapped_column(
        "benefitid", Integer, Sequence("contract_benefit_benefitid_seq"),
        primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        "contractid", Integer, ForeignKey("contract.contractid"))
    benefit_name: Mapped[str] = mapped_column("benefitname", String(100))
    benefit_type: Mapped[str | None] = mapped_column("benefittype", String(30))
    effective_date: Mapped[date | None] = mapped_column("effectivedate", Date)
    end_date: Mapped[date | None] = mapped_column("enddate", Date)

    contract: Mapped["Contract"] = relationship(back_populates="benefits")
    premiums: Mapped[list["ContractPremium"]] = relationship(
        back_populates="benefit", cascade="all, delete-orphan")


class ContractPremium(Base):
    __tablename__ = "contract_premium"

    premium_id: Mapped[int] = mapped_column(
        "premiumid", Integer, Sequence("contract_premium_premiumid_seq"),
        primary_key=True)
    benefit_id: Mapped[int] = mapped_column(
        "benefitid", Integer, ForeignKey("contract_benefit.benefitid"))
    manager_contract_id: Mapped[int | None] = mapped_column("managercontractid", Integer)
    annualized_premium: Mapped[Decimal | None] = mapped_column(
        "annualizedpremium", Numeric(14, 2))
    year_number: Mapped[int | None] = mapped_column("yearnumber", Integer)
    effective_date: Mapped[date | None] = mapped_column("effectivedate", Date)
    end_date: Mapped[date | None] = mapped_column("enddate", Date)

    benefit: Mapped["ContractBenefit"] = relationship(back_populates="premiums")


class AccountRegionalHealthProfile(Base):
    """Read-only mapping of MV_ACCOUNT_REGIONAL_HEALTH_PROFILE.

    Mapping the materialized view lets the regional-context service use
    the same session and the same typed access as every other read,
    instead of dropping to raw SQL for one screen. The composite key
    matches the view's unique index; SQLAlchemy needs a primary key to
    identify rows, and the view has no natural single-column key.

    The view is never written through. Refresh is a maintenance
    operation issued as raw SQL, because REFRESH MATERIALIZED VIEW has no
    ORM equivalent.
    """

    __tablename__ = "mv_account_regional_health_profile"
    __table_args__ = {"info": {"is_view": True}}

    account_id: Mapped[int] = mapped_column("accountid", Integer, primary_key=True)
    geography_id: Mapped[int] = mapped_column("geographyid", Integer, primary_key=True)
    indicator_id: Mapped[int] = mapped_column("indicatorid", Integer, primary_key=True)
    observation_year: Mapped[int] = mapped_column("observationyear", Integer, primary_key=True)

    account_name: Mapped[str | None] = mapped_column("accountname", String(200))
    account_state: Mapped[str | None] = mapped_column("accountstate", String(2))
    county_fips: Mapped[str | None] = mapped_column("countyfips", String(5))
    geography_name: Mapped[str | None] = mapped_column("geographyname", String(150))
    geography_state_code: Mapped[str | None] = mapped_column("geographystatecode", String(2))
    indicator_name: Mapped[str | None] = mapped_column("indicatorname", String(300))
    disease_category: Mapped[str | None] = mapped_column("diseasecategory", String(100))
    factor_category: Mapped[str | None] = mapped_column("factorcategory", String(100))
    measure_value: Mapped[Decimal | None] = mapped_column("measurevalue", Numeric(12, 4))
    unit: Mapped[str | None] = mapped_column("unit", String(30))
    source_dataset_id: Mapped[str | None] = mapped_column("sourcedatasetid", String(10))
    account_geography_relationship: Mapped[str | None] = mapped_column(
        "accountgeographyrelationship", String(30))
    last_refreshed_at: Mapped[datetime | None] = mapped_column(
        "lastrefreshedat", DateTime(timezone=True))


# Imported late to avoid a circular import at module load: quote.py maps
# relationships back to Customer and Account.
from .quote import Quote, QuoteConversion  # noqa: E402,F401
