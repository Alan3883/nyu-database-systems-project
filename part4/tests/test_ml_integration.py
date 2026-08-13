"""ML result integration with the ODS and the quote research context."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from part4.app.db import read_session, session_scope
from part4.app.models import HealthIndicator, MLClusterSummary
from part4.app.services import (
    ml_pipeline_service as ml,
    model_review_service as review,
    quote_service,
    regional_context_service as regional,
)
from part4.app.services.errors import GovernanceError, ValidationError

REVIEWER = "pytest.analyst"


def test_active_run_is_a_completed_run():
    with read_session() as session:
        run = ml.active_run(session)
    assert run is not None
    assert run.status == "Completed"


def test_failed_runs_are_never_active():
    with read_session() as session:
        active = ml.active_run(session)
        runs = ml.run_history(session, limit=50)
    failed = [r.ml_run_id for r in runs if r.status == "Failed"]
    assert active.ml_run_id not in failed


def test_active_run_has_cluster_output():
    with read_session() as session:
        run = ml.active_run(session)
        summaries = ml.cluster_summaries(session, run.ml_run_id)
        sizes = ml.cluster_sizes(session, run.ml_run_id)
    assert summaries
    assert sum(sizes.values()) > 0
    assert all(s.top_terms for s in summaries)


def test_representative_passages_come_from_the_source_document():
    with read_session() as session:
        run = ml.active_run(session)
        summaries = ml.cluster_summaries(session, run.ml_run_id)
        passages = ml.representative_texts(session, run.ml_run_id,
                                           summaries[0].cluster_id, limit=2)
    assert passages
    assert all(p.page_number >= 1 and p.word_count > 0 for p in passages)


def test_unreviewed_cluster_is_not_an_approved_insight():
    """A mapping cannot be created before review, so nothing can leak."""
    with read_session() as session:
        run = ml.active_run(session)
        summaries = ml.cluster_summaries(session, run.ml_run_id)
        unreviewed = [s for s in summaries if not s.human_reviewed]
        indicator_id = session.scalars(select(HealthIndicator.indicator_id)).first()
    if not unreviewed:
        pytest.skip("every cluster in the active run has been reviewed")

    with pytest.raises(GovernanceError):
        with session_scope() as session:
            review.approve_indicator_mapping(
                session, run.ml_run_id, unreviewed[0].cluster_id,
                indicator_id=indicator_id, approver=REVIEWER)


def test_review_then_map_then_visible_as_approved_insight():
    """The full governed path: review, map, the insight appears, and
    withdrawing the review withdraws the insight again.

    The test works on the run's *last* cluster and restores that cluster's
    original state afterwards, so it cannot disturb an approval an analyst
    made through the interface. A suite that silently retires production
    approvals would be worse than no suite.
    """
    with read_session() as session:
        run = ml.active_run(session)
        summaries = ml.cluster_summaries(session, run.ml_run_id)
        target = summaries[-1]
        cluster_id = target.cluster_id
        original = {
            "human_reviewed": target.human_reviewed,
            "reviewed_by": target.reviewed_by,
            "reviewed_at": target.reviewed_at,
            "interpretation": target.business_interpretation,
        }
        # An indicator that actually appears in some account's profile, so
        # the approved theme has somewhere to surface.
        accounts = regional.accounts_with_context(session, limit=1)
        account_id = accounts[0]["account_id"]
        rows = regional.account_context(session, account_id, limit=1)
        indicator_id = rows[0].indicator_id

    try:
        with session_scope() as session:
            review.review_cluster(
                session, run.ml_run_id, cluster_id, reviewer=REVIEWER,
                decision="approve",
                interpretation="Test interpretation recorded by the automated suite.")
            review.approve_indicator_mapping(
                session, run.ml_run_id, cluster_id, indicator_id=indicator_id,
                approver=REVIEWER, notes="Automated test mapping")

        with read_session() as session:
            index = regional.approved_theme_index(session, run.ml_run_id)
            rows = regional.account_context(session, account_id,
                                            ml_run_id=run.ml_run_id, limit=5)
        assert index.get(indicator_id, {}).get("cluster_id") == cluster_id
        assert any(r.approved_theme for r in rows)

        # Withdrawing the review must also withdraw the insight.
        with session_scope() as session:
            review.review_cluster(session, run.ml_run_id, cluster_id,
                                  reviewer=REVIEWER, decision="reject",
                                  interpretation=None)
        with read_session() as session:
            summary = review.get_summary(session, run.ml_run_id, cluster_id)
            mappings = [m for m in summary.indicator_maps if m.is_active]
        assert not summary.human_reviewed
        assert not mappings
    finally:
        with session_scope() as session:
            summary = review.get_summary(session, run.ml_run_id, cluster_id)
            summary.human_reviewed = original["human_reviewed"]
            summary.reviewed_by = original["reviewed_by"]
            summary.reviewed_at = original["reviewed_at"]
            summary.business_interpretation = original["interpretation"]
            for mapping in summary.indicator_maps:
                if mapping.approved_by == REVIEWER:
                    session.delete(mapping)


def test_regional_context_never_changes_a_premium(accepted_quote):
    """Reading regional context leaves the estimated premium untouched."""
    with read_session() as session:
        quote = quote_service.get_quote(session, accepted_quote, eager=False)
        before = Decimal(quote.estimated_premium or 0)
        account_id = quote.account_id
        run = ml.active_run(session)
        regional.account_context(session, account_id,
                                 ml_run_id=run.ml_run_id if run else None)
    with read_session() as session:
        after = Decimal(
            quote_service.get_quote(session, accepted_quote, eager=False)
            .estimated_premium or 0)
    assert after == before


def test_pricing_cannot_see_ml_or_regional_data():
    """The pricing function's inputs are limited by its signature.

    demonstration_premium takes a limit and a deductible. There is no
    parameter through which a cluster, an indicator, or an observation
    could reach it.
    """
    import inspect as pyinspect
    params = list(pyinspect.signature(quote_service.demonstration_premium).parameters)
    assert params == ["coverage_limit", "deductible"]

    source = pyinspect.getsource(quote_service.demonstration_premium)
    for forbidden in ("cluster", "indicator", "ml_run", "observation", "regional"):
        assert forbidden not in source.lower().split("\"\"\"")[-1]


def test_review_status_counts_match_the_summaries():
    with read_session() as session:
        run = ml.active_run(session)
        status = ml.review_status(session, run.ml_run_id)
        summaries = ml.cluster_summaries(session, run.ml_run_id)
    assert status.total_clusters == len(summaries)
    assert status.reviewed_clusters == sum(1 for s in summaries if s.human_reviewed)


def test_lineage_from_cluster_back_to_source_asset():
    """A run names the asset it trained on, and the asset names its file."""
    with read_session() as session:
        run = ml.active_run(session)
        asset = ml.current_source_asset(session)
        metrics = run.metrics_json or {}
    if "source_asset_id" not in metrics:
        pytest.skip("the active run predates Part IV lineage capture")
    assert metrics["source_sha256"]
    assert asset is not None and asset.relative_path
