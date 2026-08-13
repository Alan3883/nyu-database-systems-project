"""Query behaviour of the application's read paths.

The point of these tests is to hold the loader strategies in place. An ORM
makes it easy to add an attribute to a template and silently turn one query
into fifty; a test that asserts a statement count catches that in CI rather
than in production.

The numeric measurements that go into the report are produced by
scripts/measure_part4_queries.py, which writes
part4/evidence/query_performance.csv.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from part4.app.db import count_queries, read_session
from part4.app.models import Quote
from part4.app.services import (
    ml_pipeline_service as ml,
    policy_service,
    quote_service,
    regional_context_service as regional,
)


def _render(quote: Quote) -> None:
    """Touch every attribute the quote detail template reads."""
    _ = quote.customer.display_name
    _ = quote.account.account_name if quote.account else None
    _ = [(c.coverage_name, c.proposed_premium) for c in quote.coverages]
    _ = [(h.new_status, h.changed_by) for h in quote.status_history]
    _ = [(f.source_type, f.factor_value) for f in quote.risk_factors]
    _ = quote.authorized_payment
    _ = quote.conversion.contract_id if quote.conversion else None


def test_quote_list_does_not_scale_queries_with_rows():
    """The N+1 the list page would have: one SELECT per customer name.

    Both sides run the identical query, differing only in the loader
    strategy, and both use a fresh session so the identity map cannot hide
    the effect. The ordering deliberately selects rows belonging to
    distinct customers; a page showing 25 quotes from one customer would
    lazy-load that customer once and show no difference at all.
    """
    base = select(Quote).order_by(Quote.quote_id).limit(25)

    with read_session() as session:
        with count_queries() as lazy:
            for row in session.scalars(base):
                _ = row.customer.display_name
        lazy_count = lazy.count

    with read_session() as session:
        with count_queries() as eager:
            for row in session.scalars(base.options(selectinload(Quote.customer))):
                _ = row.customer.display_name
        eager_count = eager.count

    assert eager_count < lazy_count
    # One statement for the quotes, one for all their customers.
    assert eager_count == 2
    assert lazy_count > 20


def test_quote_detail_is_a_bounded_number_of_statements(accepted_quote):
    """One quote aggregate: eager loading bounds the count, it does not cut it.

    The detail page reads seven relationships of a single quote. Lazy
    loading issues one statement per relationship on first access, and
    selectinload issues one per relationship up front, so both come to the
    same number. There is no N+1 here and the tests do not pretend there
    is one: the page's guarantee is that the count is fixed and small, and
    stays that way when the aggregate grows more coverage or history rows.

    The measurable ORM win is on the list page, where the row count drives
    the statement count. See test_quote_list_does_not_scale_queries_with_rows.
    """
    with read_session() as session:
        with count_queries() as lazy:
            quote = quote_service.get_quote(session, accepted_quote, eager=False)
            _render(quote)
        lazy_count = lazy.count

    with read_session() as session:
        with count_queries() as eager:
            quote = quote_service.get_quote(session, accepted_quote, eager=True)
            _render(quote)
        eager_count = eager.count

    assert eager_count <= lazy_count
    # One root SELECT plus one per eagerly loaded relationship.
    assert eager_count <= 8


def test_policy_detail_loads_benefits_and_premiums_together(accepted_quote):
    from part4.app.db import session_scope
    with session_scope() as session:
        contract = policy_service.issue_policy(
            session, accepted_quote, actor="pytest.runner")
        contract_id = contract.contract_id

    with read_session() as session:
        with count_queries() as trace:
            contract = policy_service.get_contract(session, contract_id)
            _ = [(b.benefit_name, [p.annualized_premium for p in b.premiums])
                 for b in contract.benefits]
            _ = contract.account.account_name
    assert trace.count <= 6


def test_regional_context_is_one_statement_from_the_materialized_view():
    with read_session() as session:
        accounts = regional.accounts_with_context(session, limit=1)
        account_id = accounts[0]["account_id"]
        with count_queries() as trace:
            rows = regional.account_context(session, account_id, limit=10)
            _ = [(r.indicator_name, r.measure_value) for r in rows]
    # One SELECT against the view. No approved-theme lookup is issued when
    # no run id is supplied.
    assert trace.count == 1
    assert any("mv_account_regional_health_profile" in s.lower()
               for s in trace.statements)


def test_regional_context_with_themes_is_two_statements():
    with read_session() as session:
        run = ml.active_run(session)
        accounts = regional.accounts_with_context(session, limit=1)
        with count_queries() as trace:
            regional.account_context(session, accounts[0]["account_id"],
                                     ml_run_id=run.ml_run_id, limit=10)
    assert trace.count == 2


def test_ml_review_page_does_not_query_per_cluster():
    with read_session() as session:
        run = ml.active_run(session)
        with count_queries() as trace:
            summaries = ml.cluster_summaries(session, run.ml_run_id)
            for summary in summaries:
                _ = [m.indicator.indicator_name if m.indicator else None
                     for m in summary.indicator_maps]
    # Summaries, their mappings, and the mapped indicators: three
    # statements regardless of how many clusters the run produced.
    assert trace.count <= 3


def test_dashboard_counts_in_one_grouped_query():
    with read_session() as session:
        with count_queries() as trace:
            counts = quote_service.dashboard_counts(session)
    assert trace.count == 1
    assert "group by" in trace.statements[0].lower()
    assert counts["Total"] > 0


def test_result_sets_are_bounded():
    """No screen issues an unbounded SELECT."""
    with read_session() as session:
        with count_queries() as trace:
            quote_service.list_quotes(session)
            regional.portfolio_summary(session)
            ml.run_history(session)
    for statement in trace.statements:
        lowered = statement.lower()
        # A selectin loader's follow-up query is bounded by the primary
        # keys of the parent rows, which are themselves already limited.
        if "primary_keys_" in lowered:
            continue
        assert "limit" in lowered, statement


def test_queries_are_parameterised_not_interpolated(accepted_quote):
    """Values travel as bind parameters, which is what stops injection."""
    with read_session() as session:
        with count_queries() as trace:
            quote_service.get_quote(session, accepted_quote, eager=False)
    root = trace.statements[0]
    assert "%(" in root or "$1" in root or ":" in root
    assert str(accepted_quote) not in root
