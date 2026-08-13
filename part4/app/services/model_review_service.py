"""Human review of model output, and approval of indicator mappings.

Two governance rules are enforced here rather than left to the interface:

  1. A review requires a named reviewer. The database check constraint
     ck_mlcs_review keeps HumanReviewed, ReviewedAt, and ReviewedBy
     consistent with each other; it cannot tell whether the name is real,
     so the service rejects blank and placeholder values before the write.

  2. A cluster cannot be mapped to a health indicator until it has been
     reviewed. Approving an interpretation that nobody has read would make
     the review gate decorative.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import HealthIndicator, MLClusterIndicatorMap, MLClusterSummary
from .errors import GovernanceError, NotFound, ValidationError

log = logging.getLogger("part4.review")

# Names that are not accountable identities.
_REJECTED_REVIEWERS = {"", "n/a", "na", "none", "unknown", "anonymous", "-", "tbd"}


def _validate_reviewer(name: str | None) -> str:
    if name is None:
        raise ValidationError("A reviewer name is required.")
    cleaned = name.strip()
    if cleaned.lower() in _REJECTED_REVIEWERS or len(cleaned) < 3:
        raise ValidationError(
            "A real reviewer name is required. Approval is an accountable act.")
    return cleaned[:100]


def get_summary(session: Session, ml_run_id: int, cluster_id: int) -> MLClusterSummary:
    summary = session.get(MLClusterSummary, (ml_run_id, cluster_id))
    if summary is None:
        raise NotFound(f"Cluster {cluster_id} of run {ml_run_id} does not exist.")
    return summary


def review_cluster(session: Session, ml_run_id: int, cluster_id: int, *,
                   reviewer: str, decision: str,
                   interpretation: str | None) -> MLClusterSummary:
    """Record an analyst's decision on one cluster.

    decision 'approve' marks the interpretation reviewed and fit for
    business context. decision 'reject' clears the review flag, which also
    deactivates any mapping that was built on it: an insight cannot stay
    approved once its interpretation is withdrawn.
    """
    reviewer_name = _validate_reviewer(reviewer)
    summary = get_summary(session, ml_run_id, cluster_id)

    if decision == "approve":
        if not (interpretation or "").strip():
            raise ValidationError(
                "An approved cluster needs a written business interpretation.")
        summary.business_interpretation = interpretation.strip()
        summary.human_reviewed = True
        summary.reviewed_at = datetime.now(timezone.utc)
        summary.reviewed_by = reviewer_name
        log.info("Cluster %d of run %d approved by %s", cluster_id, ml_run_id,
                 reviewer_name)
    elif decision == "reject":
        summary.business_interpretation = (interpretation or "").strip() or None
        summary.human_reviewed = False
        # The check constraint requires both audit columns to be NULL when
        # the flag is FALSE, so a rejection genuinely resets the record.
        summary.reviewed_at = None
        summary.reviewed_by = None
        for mapping in list(summary.indicator_maps):
            mapping.is_active = False
        log.info("Cluster %d of run %d rejected by %s", cluster_id, ml_run_id,
                 reviewer_name)
    else:
        raise ValidationError(f"Unknown review decision {decision!r}.")

    session.flush()
    return summary


def approve_indicator_mapping(session: Session, ml_run_id: int, cluster_id: int, *,
                              indicator_id: int, approver: str,
                              notes: str | None = None) -> MLClusterIndicatorMap:
    """Link a reviewed cluster to an existing HEALTH_INDICATOR."""
    approver_name = _validate_reviewer(approver)
    summary = get_summary(session, ml_run_id, cluster_id)

    if not summary.human_reviewed:
        raise GovernanceError(
            "This cluster has not been reviewed. Review the interpretation "
            "before mapping it to a health indicator.")

    indicator = session.get(HealthIndicator, indicator_id)
    if indicator is None:
        raise NotFound(f"Health indicator {indicator_id} does not exist.")

    existing = session.scalars(
        select(MLClusterIndicatorMap)
        .where(MLClusterIndicatorMap.ml_run_id == ml_run_id)
        .where(MLClusterIndicatorMap.cluster_id == cluster_id)
        .where(MLClusterIndicatorMap.health_indicator_id == indicator_id)
    ).one_or_none()

    if existing is not None:
        # Re-approving an existing pair updates the audit fields rather
        # than stacking duplicate rows, which uq_mcim_active forbids.
        existing.is_active = True
        existing.approved_by = approver_name
        existing.approved_at = datetime.now(timezone.utc)
        existing.review_notes = (notes or "").strip()[:500] or existing.review_notes
        session.flush()
        return existing

    mapping = MLClusterIndicatorMap(
        ml_run_id=ml_run_id,
        cluster_id=cluster_id,
        health_indicator_id=indicator_id,
        approved_by=approver_name,
        approved_at=datetime.now(timezone.utc),
        review_notes=(notes or "").strip()[:500] or None,
        is_active=True,
    )
    session.add(mapping)
    session.flush()
    log.info("Mapped cluster %d of run %d to indicator %d by %s",
             cluster_id, ml_run_id, indicator_id, approver_name)
    return mapping


def retire_mapping(session: Session, mapping_id: int, *, actor: str) -> MLClusterIndicatorMap:
    """Deactivate a mapping without deleting the audit record."""
    _validate_reviewer(actor)
    mapping = session.get(MLClusterIndicatorMap, mapping_id)
    if mapping is None:
        raise NotFound(f"Mapping {mapping_id} does not exist.")
    mapping.is_active = False
    session.flush()
    return mapping


def active_mappings(session: Session, ml_run_id: int) -> list[MLClusterIndicatorMap]:
    return list(session.scalars(
        select(MLClusterIndicatorMap)
        .where(MLClusterIndicatorMap.ml_run_id == ml_run_id)
        .where(MLClusterIndicatorMap.is_active.is_(True))
        .order_by(MLClusterIndicatorMap.cluster_id)
    ))
