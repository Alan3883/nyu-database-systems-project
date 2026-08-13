"""Measure the application's real query behaviour.

    python3 scripts/measure_part4_queries.py

For each of the five application read paths this records, from the live
database:

  * the number of SQL statements the path emits,
  * the total time spent in the driver for those statements,
  * the wall-clock time of the whole path,
  * whether an eager-loading strategy changes the statement count,
  * the PostgreSQL execution plan and the index chosen for the path's
    primary statement.

Outputs
    part4/evidence/query_performance.csv     one row per measurement
    part4/evidence/query_plans.txt           EXPLAIN ANALYZE output
    part4/evidence/orm_sql_emitted.txt       the SQL SQLAlchemy generated

Every number here comes from a run against the Part III database with its
real data. Timings on a laptop vary between runs; the statement counts do
not, and they are the figure the report relies on.
"""

from __future__ import annotations

import csv
import statistics
import sys
import time
from pathlib import Path

# part4/scripts/<file> -> part4 -> the course workspace, which must be on
# sys.path so `import part4...` resolves.
PART4 = Path(__file__).resolve().parent.parent
WORKSPACE = PART4.parent
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from part4.app.db import ENGINE, count_queries, read_session  # noqa: E402
from part4.app.models import Contract, Quote  # noqa: E402
from part4.app.services import (  # noqa: E402
    ml_pipeline_service as ml,
    policy_service,
    quote_service,
    regional_context_service as regional,
)

EVIDENCE = PART4 / "evidence"
REPEATS = 7


def timed(fn, *args, **kwargs) -> tuple[int, float, float, list[str]]:
    """Run fn once and return (statements, driver_ms, wall_ms, sql)."""
    with count_queries() as trace:
        started = time.perf_counter()
        fn(*args, **kwargs)
        wall = (time.perf_counter() - started) * 1000
    return trace.count, trace.total_seconds * 1000, wall, trace.statements


def measure(name: str, fn, *, repeats: int = REPEATS) -> dict:
    """Run a path several times and keep the median wall time."""
    walls, drivers, counts, sql = [], [], [], []
    for _ in range(repeats):
        count, driver, wall, statements = timed(fn)
        counts.append(count)
        drivers.append(driver)
        walls.append(wall)
        sql = statements
    assert len(set(counts)) == 1, f"{name} emitted a varying statement count: {counts}"
    return {
        "path": name,
        "statements": counts[0],
        "driver_ms_median": round(statistics.median(drivers), 3),
        "wall_ms_median": round(statistics.median(walls), 3),
        "wall_ms_min": round(min(walls), 3),
        "sql": sql,
    }


# ---------------------------------------------------------------------
# The five application read paths
# ---------------------------------------------------------------------
def path_dashboard():
    with read_session() as session:
        quote_service.dashboard_counts(session)
        run = ml.active_run(session)
        ml.review_status(session, run.ml_run_id if run else None)
        ml.current_source_asset(session)
        for quote in quote_service.list_quotes(session, limit=8):
            _ = quote.customer.display_name


def path_quote_detail_lazy(quote_id: int):
    with read_session() as session:
        quote = quote_service.get_quote(session, quote_id, eager=False)
        _touch(quote)


def path_quote_detail_eager(quote_id: int):
    with read_session() as session:
        quote = quote_service.get_quote(session, quote_id, eager=True)
        _touch(quote)


def _touch(quote) -> None:
    _ = quote.customer.display_name
    _ = quote.account.account_name if quote.account else None
    _ = [c.coverage_name for c in quote.coverages]
    _ = [h.new_status for h in quote.status_history]
    _ = [f.factor_value for f in quote.risk_factors]
    _ = quote.authorized_payment
    _ = quote.conversion.contract_id if quote.conversion else None


def path_quote_list_lazy():
    base = select(Quote).order_by(Quote.quote_id).limit(25)
    with read_session() as session:
        for row in session.scalars(base):
            _ = row.customer.display_name


def path_quote_list_eager():
    base = (select(Quote).order_by(Quote.quote_id).limit(25)
            .options(selectinload(Quote.customer)))
    with read_session() as session:
        for row in session.scalars(base):
            _ = row.customer.display_name


def path_policy_detail(contract_id: int):
    with read_session() as session:
        contract = policy_service.get_contract(session, contract_id)
        _ = [(b.benefit_name, [p.annualized_premium for p in b.premiums])
             for b in contract.benefits]


def path_regional_context(account_id: int, run_id: int | None):
    with read_session() as session:
        rows = regional.account_context(session, account_id, ml_run_id=run_id, limit=15)
        _ = [(r.indicator_name, r.approved_theme) for r in rows]


def path_regional_context_join(account_id: int):
    """The same read without the materialized view, for comparison."""
    with read_session() as session:
        session.execute(text("""
            SELECT hi.IndicatorName, ho.MeasureValue, ho.ObservationYear,
                   g.CountyFIPS, g.GeographyName
            FROM ACCOUNT a
            JOIN ACCOUNT_GEOGRAPHY  ag ON ag.AccountID   = a.AccountID
            JOIN GEOGRAPHIC_AREA     g ON g.GeographyID  = ag.GeographyID
            JOIN HEALTH_OBSERVATION ho ON ho.GeographyID = g.GeographyID
            JOIN HEALTH_INDICATOR   hi ON hi.IndicatorID = ho.IndicatorID
            WHERE a.AccountID = :account
              AND (ag.EndDate IS NULL OR ag.EndDate >= CURRENT_DATE)
            ORDER BY ho.MeasureValue DESC NULLS LAST
            LIMIT 15
        """), {"account": account_id}).all()


def path_ml_review(run_id: int):
    with read_session() as session:
        summaries = ml.cluster_summaries(session, run_id)
        for summary in summaries:
            _ = [m.indicator.indicator_name if m.indicator else None
                 for m in summary.indicator_maps]
        ml.cluster_sizes(session, run_id)


# ---------------------------------------------------------------------
def explain(label: str, sql: str, params: dict) -> str:
    with ENGINE.connect() as conn:
        rows = conn.execute(text("EXPLAIN (ANALYZE, BUFFERS) " + sql), params).all()
    plan = "\n".join(r[0] for r in rows)
    return f"--- {label} ---\n{sql.strip()}\n\n{plan}\n"


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)

    with read_session() as session:
        run = ml.active_run(session)
        run_id = run.ml_run_id if run else None
        accounts = regional.accounts_with_context(session, limit=1)
        account_id = accounts[0]["account_id"]
        converted = session.scalars(
            select(Quote.quote_id).where(Quote.quote_status == "Converted")
            .order_by(Quote.quote_id.desc()).limit(1)).first()
        quote_id = converted or session.scalars(
            select(Quote.quote_id).order_by(Quote.quote_id.desc()).limit(1)).first()
        contract_id = session.scalars(
            select(Contract.contract_id).order_by(Contract.contract_id.desc())
            .limit(1)).first()

    measurements = [
        measure("1. Dashboard", path_dashboard),
        measure("2a. Quote list, lazy loading (before)", path_quote_list_lazy),
        measure("2b. Quote list, selectinload (after)", path_quote_list_eager),
        measure("3a. Quote detail, lazy loading", lambda: path_quote_detail_lazy(quote_id)),
        measure("3b. Quote detail, selectinload", lambda: path_quote_detail_eager(quote_id)),
        measure("4. Policy detail", lambda: path_policy_detail(contract_id)),
        measure("5a. Regional context, materialized view",
                lambda: path_regional_context(account_id, run_id)),
        measure("5b. Regional context, five-table join",
                lambda: path_regional_context_join(account_id)),
        measure("6. ML review page", lambda: path_ml_review(run_id)),
    ]

    csv_path = EVIDENCE / "query_performance.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["path", "sql_statements", "driver_ms_median",
                         "wall_ms_median", "wall_ms_min", "repeats"])
        for row in measurements:
            writer.writerow([row["path"], row["statements"],
                             row["driver_ms_median"], row["wall_ms_median"],
                             row["wall_ms_min"], REPEATS])

    sql_path = EVIDENCE / "orm_sql_emitted.txt"
    with sql_path.open("w", encoding="utf-8") as handle:
        handle.write("SQL emitted by SQLAlchemy for each application read path.\n")
        handle.write("Captured with part4.app.db.count_queries against the live "
                     "database.\n\n")
        for row in measurements:
            handle.write("=" * 78 + "\n")
            handle.write(f"{row['path']}  -  {row['statements']} statement(s)\n")
            handle.write("=" * 78 + "\n")
            for i, statement in enumerate(row["sql"], start=1):
                handle.write(f"[{i}] {statement}\n\n")

    plans = [
        explain("Dashboard: quote counts by status",
                "SELECT quotestatus, count(*) FROM quote GROUP BY quotestatus", {}),
        explain("Quote detail: quote header by id",
                "SELECT * FROM quote WHERE quoteid = :q", {"q": quote_id}),
        explain("Quote detail: status history for one quote",
                "SELECT * FROM quote_status_history WHERE quoteid = :q "
                "ORDER BY changedat", {"q": quote_id}),
        explain("Policy detail: benefits and premiums for one contract",
                "SELECT b.*, p.* FROM contract_benefit b "
                "LEFT JOIN contract_premium p ON p.benefitid = b.benefitid "
                "WHERE b.contractid = :c", {"c": contract_id}),
        explain("Regional context: materialized view for one account",
                "SELECT * FROM mv_account_regional_health_profile "
                "WHERE accountid = :a ORDER BY measurevalue DESC NULLS LAST "
                "LIMIT 15", {"a": account_id}),
        explain("Regional context: the same read as a five-table join",
                """SELECT hi.IndicatorName, ho.MeasureValue, ho.ObservationYear
                   FROM ACCOUNT a
                   JOIN ACCOUNT_GEOGRAPHY  ag ON ag.AccountID   = a.AccountID
                   JOIN GEOGRAPHIC_AREA     g ON g.GeographyID  = ag.GeographyID
                   JOIN HEALTH_OBSERVATION ho ON ho.GeographyID = g.GeographyID
                   JOIN HEALTH_INDICATOR   hi ON hi.IndicatorID = ho.IndicatorID
                   WHERE a.AccountID = :a
                   ORDER BY ho.MeasureValue DESC NULLS LAST LIMIT 15""",
                {"a": account_id}),
        explain("ML review: cluster summaries for one run",
                "SELECT * FROM ml_cluster_summary WHERE mlrunid = :r "
                "ORDER BY clusterid", {"r": run_id}),
        explain("ML review: approved indicator mappings for one run",
                "SELECT * FROM ml_cluster_indicator_map "
                "WHERE mlrunid = :r AND isactive", {"r": run_id}),
    ]
    (EVIDENCE / "query_plans.txt").write_text(
        "EXPLAIN (ANALYZE, BUFFERS) for the Part IV application read paths.\n"
        "Run against the live part3 database.\n\n" + "\n".join(plans))

    print(f"{'path':<44}{'stmts':>7}{'driver ms':>12}{'wall ms':>10}")
    print("-" * 73)
    for row in measurements:
        print(f"{row['path']:<44}{row['statements']:>7}"
              f"{row['driver_ms_median']:>12}{row['wall_ms_median']:>10}")
    print("-" * 73)

    lazy_list = next(r for r in measurements if r["path"].startswith("2a"))
    eager_list = next(r for r in measurements if r["path"].startswith("2b"))
    mv = next(r for r in measurements if r["path"].startswith("5a"))
    join = next(r for r in measurements if r["path"].startswith("5b"))
    print(f"\nORM optimization  : quote list {lazy_list['statements']} -> "
          f"{eager_list['statements']} statements "
          f"({lazy_list['wall_ms_median']} -> {eager_list['wall_ms_median']} ms)")
    print(f"Materialization   : regional context {join['wall_ms_median']} ms via the "
          f"five-table join, {mv['wall_ms_median']} ms via the view")
    print(f"\nWritten: {csv_path.relative_to(WORKSPACE)}, "
          f"{sql_path.relative_to(WORKSPACE)}, "
          f"{(EVIDENCE / 'query_plans.txt').relative_to(WORKSPACE)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
