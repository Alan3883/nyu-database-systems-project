"""SQLAlchemy ORM mappings for the Part III physical schema.

The mappings describe tables that already exist. Part IV does not run ORM
migrations against the Part II or Part III schema: the authoritative DDL
stays in database/physical/*.sql and part4/db/01_part4_extension.sql, and
these classes are a typed view onto it. Base.metadata.create_all is never
called by the application.

Only the tables the application actually reads or writes are mapped.
Mapping all 37 would add maintenance cost with no caller.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for every Part IV mapping."""


from .insurance import (  # noqa: E402
    Account,
    AccountGeography,
    AccountRegionalHealthProfile,
    Associate,
    Contract,
    ContractBenefit,
    ContractPremium,
    Customer,
    GeographicArea,
    HealthIndicator,
    HealthObservation,
)
from .ml import (  # noqa: E402
    DataAsset,
    Dataset,
    DocumentChunk,
    MLClusterIndicatorMap,
    MLClusterResult,
    MLClusterSummary,
    MLRun,
)
from .quote import (  # noqa: E402
    PaymentAuthorization,
    Quote,
    QuoteConversion,
    QuoteCoverage,
    QuoteRiskFactor,
    QuoteStatusHistory,
)

__all__ = [
    "Base",
    "Account",
    "AccountGeography",
    "AccountRegionalHealthProfile",
    "Associate",
    "Contract",
    "ContractBenefit",
    "ContractPremium",
    "Customer",
    "GeographicArea",
    "HealthIndicator",
    "HealthObservation",
    "DataAsset",
    "Dataset",
    "DocumentChunk",
    "MLClusterIndicatorMap",
    "MLClusterResult",
    "MLClusterSummary",
    "MLRun",
    "PaymentAuthorization",
    "Quote",
    "QuoteConversion",
    "QuoteCoverage",
    "QuoteRiskFactor",
    "QuoteStatusHistory",
]
