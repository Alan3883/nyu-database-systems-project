"""Regional research context for an account.

Data path, unchanged from Part II and Part III:

    ACCOUNT -> ACCOUNT_GEOGRAPHY -> GEOGRAPHIC_AREA
            -> HEALTH_OBSERVATION -> HEALTH_INDICATOR

The five-way join is served from MV_ACCOUNT_REGIONAL_HEALTH_PROFILE, the
materialized view built in Part III for exactly this read.

What this module returns is county-level public data. It describes the
area an account sits in. It says nothing about any person, and no caller
may treat it as an individual health record, an eligibility test, or a
rating input. The premium calculation in quote_service does not import
this module, and no function here writes to QUOTE.EstimatedPremium.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..models import (
    Account,
    AccountRegionalHealthProfile as Profile,
    HealthIndicator,
    MLClusterIndicatorMap,
    MLClusterSummary,
)

log = logging.getLogger("part4.regional")

DISCLAIMER = ("Regional aggregate research context. Not used to determine "
              "individual eligibility or premium.")


@dataclass
class RegionalIndicator:
    """One county-level observation, plus any approved model theme."""

    indicator_id: int
    indicator_name: str
    factor_category: str | None
    disease_category: str | None
    measure_value: Decimal | None
    unit: str | None
    observation_year: int | None
    county_fips: str | None
    geography_name: str | None
    source_dataset_id: str | None
    approved_theme: str | None = None
    theme_run_id: int | None = None
    theme_cluster_id: int | None = None
    theme_approved_by: str | None = None


def approved_theme_index(session: Session, ml_run_id: int | None) -> dict[int, dict]:
    """Map HealthIndicatorID -> approved theme, for one model run.

    Two conditions must both hold before a theme appears here:
      * ML_CLUSTER_SUMMARY.HumanReviewed is TRUE, and
      * ML_CLUSTER_INDICATOR_MAP.IsActive is TRUE.

    They are separate gates on purpose. A mapping proposed before review,
    or left active after a review is withdrawn, must not leak into the
    business view on the strength of the other flag alone.
    """
    if ml_run_id is None:
        return {}
    rows = session.execute(
        select(
            MLClusterIndicatorMap.health_indicator_id,
            MLClusterIndicatorMap.cluster_id,
            MLClusterIndicatorMap.ml_run_id,
            MLClusterIndicatorMap.approved_by,
            MLClusterIndicatorMap.review_notes,
            MLClusterSummary.cluster_label,
            MLClusterSummary.business_interpretation,
        )
        .join(MLClusterSummary,
              (MLClusterSummary.ml_run_id == MLClusterIndicatorMap.ml_run_id) &
              (MLClusterSummary.cluster_id == MLClusterIndicatorMap.cluster_id))
        .where(MLClusterIndicatorMap.ml_run_id == ml_run_id)
        .where(MLClusterIndicatorMap.is_active.is_(True))
        .where(MLClusterSummary.human_reviewed.is_(True))
    ).all()

    index: dict[int, dict] = {}
    for row in rows:
        index[row.health_indicator_id] = {
            "cluster_id": row.cluster_id,
            "ml_run_id": row.ml_run_id,
            "approved_by": row.approved_by,
            "label": row.business_interpretation or row.cluster_label,
            "notes": row.review_notes,
        }
    return index


def account_context(session: Session, account_id: int, *,
                    ml_run_id: int | None = None,
                    limit: int = 12) -> list[RegionalIndicator]:
    """Return the regional profile for one account.

    Reads the materialized view, one statement, indexed on AccountID.
    Ordered so the highest-value indicators appear first, and bounded by
    `limit`: an unbounded result set on a screen is an ORM performance
    trap regardless of how the rows are fetched.
    """
    rows = session.execute(
        select(Profile)
        .where(Profile.account_id == account_id)
        .order_by(Profile.measure_value.desc().nullslast())
        .limit(limit)
    ).scalars().all()

    themes = approved_theme_index(session, ml_run_id)
    out: list[RegionalIndicator] = []
    for row in rows:
        theme = themes.get(row.indicator_id)
        out.append(RegionalIndicator(
            indicator_id=row.indicator_id,
            indicator_name=row.indicator_name or "",
            factor_category=row.factor_category,
            disease_category=row.disease_category,
            measure_value=row.measure_value,
            unit=row.unit,
            observation_year=row.observation_year,
            county_fips=row.county_fips,
            geography_name=row.geography_name,
            source_dataset_id=row.source_dataset_id,
            approved_theme=(theme or {}).get("label"),
            theme_run_id=(theme or {}).get("ml_run_id"),
            theme_cluster_id=(theme or {}).get("cluster_id"),
            theme_approved_by=(theme or {}).get("approved_by"),
        ))
    return out


def portfolio_summary(session: Session, limit: int = 10) -> list[dict]:
    """Indicator averages across all accounts, for the research page.

    Aggregation runs in the database. Pulling every profile row into
    Python to average it would move tens of thousands of rows over the
    wire to produce ten.
    """
    rows = session.execute(
        select(
            Profile.indicator_id,
            Profile.indicator_name,
            Profile.factor_category,
            func.count().label("observations"),
            func.round(func.avg(Profile.measure_value), 2).label("avg_value"),
            func.count(func.distinct(Profile.county_fips)).label("counties"),
        )
        .group_by(Profile.indicator_id, Profile.indicator_name, Profile.factor_category)
        .order_by(func.avg(Profile.measure_value).desc())
        .limit(limit)
    ).all()
    return [dict(r._mapping) for r in rows]


def accounts_with_context(session: Session, limit: int = 50) -> list[dict]:
    """Accounts that have a regional profile, for the context page picker."""
    rows = session.execute(
        select(
            Profile.account_id,
            Profile.account_name,
            Profile.geography_name,
            Profile.county_fips,
            func.count().label("indicators"),
        )
        .group_by(Profile.account_id, Profile.account_name,
                  Profile.geography_name, Profile.county_fips)
        .order_by(Profile.account_name)
        .limit(limit)
    ).all()
    return [dict(r._mapping) for r in rows]


def refresh_materialized_view(session: Session) -> None:
    """Refresh the regional profile view.

    Raw SQL: REFRESH MATERIALIZED VIEW is a PostgreSQL maintenance command
    with no ORM equivalent. CONCURRENTLY is available because Part III
    created the required unique index.
    """
    session.execute(text(
        "REFRESH MATERIALIZED VIEW CONCURRENTLY MV_ACCOUNT_REGIONAL_HEALTH_PROFILE"))
    log.info("Refreshed MV_ACCOUNT_REGIONAL_HEALTH_PROFILE")


def indicator_choices(session: Session, limit: int = 400) -> list[HealthIndicator]:
    """Indicators an analyst may map a cluster to."""
    return list(session.scalars(
        select(HealthIndicator).order_by(HealthIndicator.indicator_name).limit(limit)))
