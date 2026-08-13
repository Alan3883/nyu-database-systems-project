"""Governance controls: review, accountability, least privilege, and privacy."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import select, text

from part4.app.config import CONFIG
from part4.app.db import ENGINE, read_session, session_scope
from part4.app.models import HealthIndicator, MLClusterIndicatorMap, Quote
from part4.app.services import (
    ml_pipeline_service as ml,
    model_review_service as review,
    quote_service,
    regional_context_service as regional,
)
from part4.app.services.errors import GovernanceError, ValidationError


# --- human review -----------------------------------------------------
@pytest.mark.parametrize("name", ["", "   ", "n/a", "none", "unknown", "-", "ab"])
def test_approval_requires_a_real_reviewer_name(name):
    with read_session() as session:
        run = ml.active_run(session)
        cluster_id = ml.cluster_summaries(session, run.ml_run_id)[0].cluster_id
    with pytest.raises(ValidationError):
        with session_scope() as session:
            review.review_cluster(session, run.ml_run_id, cluster_id,
                                  reviewer=name, decision="approve",
                                  interpretation="Some interpretation")


def test_approval_requires_a_written_interpretation():
    with read_session() as session:
        run = ml.active_run(session)
        cluster_id = ml.cluster_summaries(session, run.ml_run_id)[0].cluster_id
    with pytest.raises(ValidationError):
        with session_scope() as session:
            review.review_cluster(session, run.ml_run_id, cluster_id,
                                  reviewer="pytest.analyst", decision="approve",
                                  interpretation="   ")


def test_database_constraint_blocks_a_review_without_a_reviewer():
    """The check constraint holds even if the service is bypassed."""
    with read_session() as session:
        run = ml.active_run(session)
        cluster_id = ml.cluster_summaries(session, run.ml_run_id)[0].cluster_id
    with pytest.raises(Exception) as excinfo:
        with session_scope() as session:
            session.execute(text(
                "UPDATE ml_cluster_summary SET humanreviewed = TRUE, "
                "reviewedat = NULL, reviewedby = NULL "
                "WHERE mlrunid = :r AND clusterid = :c"),
                {"r": run.ml_run_id, "c": cluster_id})
    assert "ck_mlcs_review" in str(excinfo.value)


def test_mapping_requires_review_first():
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
                indicator_id=indicator_id, approver="pytest.analyst")


def test_every_active_mapping_has_a_named_approver():
    with read_session() as session:
        mappings = session.scalars(
            select(MLClusterIndicatorMap)
            .where(MLClusterIndicatorMap.is_active.is_(True))).all()
    for mapping in mappings:
        assert mapping.approved_by and mapping.approved_by.strip()
        assert mapping.approved_at is not None


def test_no_approved_insight_without_a_reviewed_cluster():
    """The two governance gates are enforced together, not either-or."""
    with read_session() as session:
        for run in ml.run_history(session, limit=20):
            index = regional.approved_theme_index(session, run.ml_run_id)
            summaries = {s.cluster_id: s
                         for s in ml.cluster_summaries(session, run.ml_run_id)}
            for entry in index.values():
                summary = summaries[entry["cluster_id"]]
                assert summary.human_reviewed
                assert summary.reviewed_by


# --- pricing separation ----------------------------------------------
def test_ml_output_cannot_reach_the_pricing_function():
    source = Path(quote_service.__file__).read_text()
    body = source.split("def demonstration_premium", 1)[1].split("\ndef ", 1)[0]
    code = body.split('"""')[-1]
    for token in ("MLRun", "MLCluster", "HealthObservation", "regional",
                  "indicator", "measure_value"):
        assert token not in code, f"{token} appears in the pricing calculation"


def test_quote_service_does_not_import_regional_context():
    """A module cannot use data it never imports."""
    source = Path(quote_service.__file__).read_text()
    assert "import regional_context_service" not in source
    assert "from .regional_context_service" not in source


def test_regional_service_never_writes_a_premium():
    source = Path(regional.__file__).read_text()
    assert "estimated_premium" not in source
    assert "proposed_premium" not in source


# --- patient-level data ------------------------------------------------
def test_regional_context_carries_no_person_level_column():
    """The research view exposes areas and indicators, never a person."""
    from part4.app.models import AccountRegionalHealthProfile as Profile
    columns = {c.name for c in Profile.__table__.columns}
    forbidden = {"customerid", "custlastname", "custfirstname", "custdob",
                 "ssn_tin", "patientid", "memberid", "diagnosis"}
    assert not columns & forbidden


def test_customer_identifiers_are_not_mapped():
    from part4.app.models import Customer
    columns = {c.name for c in Customer.__table__.columns}
    assert "ssn_tin" not in columns


def test_regional_rows_are_area_level():
    with read_session() as session:
        accounts = regional.accounts_with_context(session, limit=1)
        rows = regional.account_context(session, accounts[0]["account_id"], limit=5)
    assert rows
    for row in rows:
        # Every row is anchored to a county, and none names an individual.
        assert row.county_fips or row.geography_name


def test_risk_factors_from_public_data_are_labelled_as_aggregates():
    with read_session() as session:
        factors = session.execute(text(
            "SELECT sourcetype, sourcereference FROM quote_risk_factor "
            "WHERE riskfactortype = 'RegionalResearchContext'")).all()
    for source_type, reference in factors:
        assert source_type == "RegionalAggregate"
        assert reference is None or "FIPS" in reference


# --- least privilege and secrets ---------------------------------------
def test_application_role_has_no_delete_or_ddl():
    with ENGINE.connect() as conn:
        privileges = {row[0] for row in conn.execute(text(
            "SELECT privilege_type FROM information_schema.role_table_grants "
            "WHERE grantee = 'part4_app_role' AND table_name = 'quote'"))}
    assert privileges
    assert "DELETE" not in privileges
    assert privileges <= {"SELECT", "INSERT", "UPDATE"}


def test_no_credentials_in_the_part4_source():
    """No password, key, or token is written into version-controlled code."""
    part4 = CONFIG.part4
    patterns = [
        re.compile(r"password\s*=\s*['\"][^'\"]{3,}['\"]", re.IGNORECASE),
        re.compile(r"AKIA[0-9A-Z]{16}"),
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    ]
    offenders = []
    for path in part4.rglob("*.py"):
        if ".env" in path.parts:
            continue
        text_content = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in patterns:
            if pattern.search(text_content):
                offenders.append(f"{path.relative_to(CONFIG.workspace)}: {pattern.pattern}")
    assert not offenders, offenders


def test_env_file_is_ignored_by_git():
    gitignore = CONFIG.part4 / ".gitignore"
    if not gitignore.exists():
        pytest.skip("repository is not yet under version control")
    content = gitignore.read_text()
    assert ".env" in content


# --- accountability -----------------------------------------------------
def test_every_quote_transition_names_who_made_it():
    with read_session() as session:
        rows = session.execute(text(
            "SELECT count(*) FROM quote_status_history "
            "WHERE changedby IS NULL OR trim(changedby) = ''")).scalar_one()
    assert rows == 0


def test_conversion_is_traceable_to_a_quote_and_an_actor():
    with read_session() as session:
        orphans = session.execute(text(
            "SELECT count(*) FROM quote_conversion qc "
            "LEFT JOIN quote q ON q.quoteid = qc.quoteid "
            "WHERE q.quoteid IS NULL")).scalar_one()
        unlogged = session.execute(text(
            "SELECT count(*) FROM quote_conversion qc "
            "WHERE NOT EXISTS (SELECT 1 FROM quote_status_history h "
            "  WHERE h.quoteid = qc.quoteid AND h.newstatus = 'Converted')"
        )).scalar_one()
    assert orphans == 0
    assert unlogged == 0
