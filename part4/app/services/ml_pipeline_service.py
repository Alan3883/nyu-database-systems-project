"""Read access to model runs, cluster output, and source-asset versions.

Definition of the active model used everywhere in Part IV:

    the ML_RUN with Status = 'Completed' and the greatest CompletedAt.

Nothing else marks a model active. A run that fails is stored with
Status = 'Failed', so it is invisible to this query and the previously
completed run keeps serving. That is the whole rollback mechanism: no
flag to flip, no state to repair.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, selectinload

from ..models import (
    DataAsset,
    DocumentChunk,
    MLClusterIndicatorMap,
    MLClusterResult,
    MLClusterSummary,
    MLRun,
)
from .errors import NotFound

log = logging.getLogger("part4.ml")

DS010 = "DS010"
UNSTRUCTURED = "unstructured document"


def active_run(session: Session) -> MLRun | None:
    """The model currently serving the application."""
    return session.scalars(
        select(MLRun)
        .where(MLRun.status == "Completed")
        .order_by(desc(MLRun.completed_at), desc(MLRun.ml_run_id))
        .limit(1)
    ).one_or_none()


def get_run(session: Session, ml_run_id: int) -> MLRun:
    run = session.get(MLRun, ml_run_id)
    if run is None:
        raise NotFound(f"ML run {ml_run_id} does not exist.")
    return run


def run_history(session: Session, limit: int = 15) -> list[MLRun]:
    return list(session.scalars(
        select(MLRun).order_by(desc(MLRun.ml_run_id)).limit(limit)))


def cluster_summaries(session: Session, ml_run_id: int) -> list[MLClusterSummary]:
    """Cluster summaries for a run, with their indicator mappings.

    selectinload on indicator_maps keeps the review page at a fixed
    statement count: one for the summaries, one for all their mappings,
    instead of one per cluster.
    """
    return list(session.scalars(
        select(MLClusterSummary)
        .where(MLClusterSummary.ml_run_id == ml_run_id)
        .options(
            selectinload(MLClusterSummary.indicator_maps)
            .selectinload(MLClusterIndicatorMap.indicator))
        .order_by(MLClusterSummary.cluster_id)
    ).unique())


def cluster_sizes(session: Session, ml_run_id: int) -> dict[int, int]:
    rows = session.execute(
        select(MLClusterResult.cluster_id, func.count())
        .where(MLClusterResult.ml_run_id == ml_run_id)
        .group_by(MLClusterResult.cluster_id)
    ).all()
    return {cid: n for cid, n in rows}


def representative_texts(session: Session, ml_run_id: int, cluster_id: int,
                         limit: int = 3) -> list[DocumentChunk]:
    """The chunks closest to a cluster centroid, as evidence for a reviewer.

    A reviewer cannot judge a theme from term lists alone; they need the
    passages the model actually grouped.
    """
    return list(session.scalars(
        select(DocumentChunk)
        .join(MLClusterResult,
              MLClusterResult.document_chunk_id == DocumentChunk.document_chunk_id)
        .where(MLClusterResult.ml_run_id == ml_run_id)
        .where(MLClusterResult.cluster_id == cluster_id)
        .order_by(MLClusterResult.distance_to_centroid)
        .limit(limit)
    ))


def current_source_asset(session: Session) -> DataAsset | None:
    """The DS010 asset version the pipeline currently treats as current."""
    return session.scalars(
        select(DataAsset)
        .where(DataAsset.dataset_id == DS010)
        .where(DataAsset.asset_type == UNSTRUCTURED)
        .where(DataAsset.status == "Stored")
        .order_by(desc(DataAsset.asset_id))
        .limit(1)
    ).one_or_none()


def source_asset_versions(session: Session, limit: int = 10) -> list[DataAsset]:
    """Every preserved version of the unstructured source, newest first."""
    return list(session.scalars(
        select(DataAsset)
        .where(DataAsset.dataset_id == DS010)
        .where(DataAsset.asset_type == UNSTRUCTURED)
        .order_by(desc(DataAsset.asset_id))
        .limit(limit)
    ))


@dataclass
class ReviewStatus:
    total_clusters: int
    reviewed_clusters: int
    approved_mappings: int

    @property
    def is_complete(self) -> bool:
        return self.total_clusters > 0 and self.reviewed_clusters == self.total_clusters

    @property
    def label(self) -> str:
        if self.total_clusters == 0:
            return "No model output"
        if self.reviewed_clusters == 0:
            return "Awaiting review"
        if self.is_complete:
            return "Review complete"
        return f"Partially reviewed ({self.reviewed_clusters}/{self.total_clusters})"


def review_status(session: Session, ml_run_id: int | None) -> ReviewStatus:
    """Aggregate review state for a run, computed in the database."""
    if ml_run_id is None:
        return ReviewStatus(0, 0, 0)
    total, reviewed = session.execute(
        select(
            func.count(),
            func.count().filter(MLClusterSummary.human_reviewed.is_(True)),
        ).where(MLClusterSummary.ml_run_id == ml_run_id)
    ).one()
    approved = session.execute(
        select(func.count())
        .select_from(MLClusterIndicatorMap)
        .where(MLClusterIndicatorMap.ml_run_id == ml_run_id)
        .where(MLClusterIndicatorMap.is_active.is_(True))
    ).scalar_one()
    return ReviewStatus(int(total), int(reviewed), int(approved))


def chunk_count(session: Session, ml_run_id: int) -> int:
    return int(session.execute(
        select(func.count()).select_from(MLClusterResult)
        .where(MLClusterResult.ml_run_id == ml_run_id)
    ).scalar_one())
