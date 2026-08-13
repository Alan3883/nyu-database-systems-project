"""Database connectivity, ORM mapping fidelity, and transaction behaviour."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError

from part4.app.db import ENGINE, check_connection, read_session, session_scope
from part4.app.models import (
    Account,
    Base,
    Contract,
    Customer,
    MLClusterIndicatorMap,
    Quote,
    QuoteStatusHistory,
)
from part4.app.services import quote_service

ACTOR = "pytest.runner"


def test_postgres_connection():
    ok, message = check_connection()
    assert ok
    assert "PostgreSQL 16" in message


def test_not_sqlite():
    """The application must run on PostgreSQL, not a stand-in."""
    assert ENGINE.dialect.name == "postgresql"


def test_every_mapped_table_exists():
    """Each ORM class maps to a table or view that is really there."""
    inspector = inspect(ENGINE)
    present = set(inspector.get_table_names()) | set(inspector.get_view_names())
    present |= {mv for mv in _matview_names()}
    mapped = {m.class_.__tablename__ for m in Base.registry.mappers}
    missing = mapped - present
    assert not missing, f"mapped but absent from the database: {sorted(missing)}"


def _matview_names() -> set[str]:
    with ENGINE.connect() as conn:
        return {row[0] for row in conn.execute(
            text("SELECT matviewname FROM pg_matviews WHERE schemaname='public'"))}


def test_mapped_columns_match_the_database():
    """Every mapped column name exists on its table, with no typos."""
    inspector = inspect(ENGINE)
    problems = []
    for mapper in Base.registry.mappers:
        table = mapper.class_.__tablename__
        try:
            actual = {c["name"] for c in inspector.get_columns(table)}
        except Exception:  # noqa: BLE001 - matview handled below
            continue
        for column in mapper.columns:
            if column.name not in actual:
                problems.append(f"{table}.{column.name}")
    assert not problems, f"mapped columns absent from the database: {problems}"


def test_part4_extension_objects_exist():
    inspector = inspect(ENGINE)
    assert "ml_cluster_indicator_map" in inspector.get_table_names()
    indexes = {i["name"] for i in inspector.get_indexes("ml_cluster_indicator_map")}
    assert "ix_mcim_run_active" in indexes


def test_expected_table_count():
    """36 Parts II-III tables plus the one Part IV table."""
    with ENGINE.connect() as conn:
        count = conn.execute(text(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema='public' AND table_type='BASE TABLE' "
            "AND table_name NOT LIKE 'perf_%'")).scalar_one()
    assert count == 37


def test_transaction_rolls_back_on_failure(ids):
    """A failure inside session_scope must leave nothing behind."""
    with read_session() as session:
        before = session.execute(select(func.count()).select_from(Quote)).scalar_one()

    with pytest.raises(RuntimeError):
        with session_scope() as session:
            quote_service.create_quote(
                session, customer_id=ids["customer_id"],
                account_id=ids["account_id"], product_line="Dental",
                requested_date=date.today(), effective_date=None,
                expiration_date=None, actor=ACTOR)
            raise RuntimeError("simulated failure after the insert")

    with read_session() as session:
        after = session.execute(select(func.count()).select_from(Quote)).scalar_one()
    assert after == before


def test_quote_and_history_commit_together(draft_quote):
    """Quote creation writes both rows or neither."""
    with read_session() as session:
        history = session.scalars(
            select(QuoteStatusHistory)
            .where(QuoteStatusHistory.quote_id == draft_quote)).all()
    assert len(history) == 1
    assert history[0].new_status == "Draft"
    assert history[0].previous_status is None


def test_check_constraint_rejects_unknown_status(draft_quote):
    """ck_quote_status is enforced by the database, not only by the service."""
    with pytest.raises(IntegrityError):
        with session_scope() as session:
            session.execute(text(
                "UPDATE quote SET quotestatus = 'Nonsense' WHERE quoteid = :q"
            ), {"q": draft_quote})


def test_foreign_key_rejects_unknown_customer():
    with pytest.raises(IntegrityError):
        with session_scope() as session:
            session.add(Quote(
                quote_number="Q4-FK-TEST",
                customer_id=999999999,
                account_id=None,
                product_line="Medical",
                quote_status="Draft",
                requested_date=date.today(),
                estimated_premium=Decimal("0"),
            ))


def test_relationship_navigation(accepted_quote):
    """Relationships resolve in both directions."""
    with read_session() as session:
        quote = quote_service.get_quote(session, accepted_quote)
        assert quote.customer.customer_id == quote.customer_id
        assert quote.coverages
        assert quote.coverages[0].quote.quote_id == quote.quote_id
        assert len(quote.status_history) >= 4


def test_connection_pool_configured():
    assert ENGINE.pool.size() >= 1
    assert ENGINE.pool._pre_ping is True
