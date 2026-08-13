"""Python test suite for the Part III database.

Verifies schema shape, Part II preservation, Part III objects, referential
integrity, and the materialized view. Skips cleanly when the PostgreSQL
container is not running.

Usage:
    python3 -m pytest database/tests/test_database.py -v
"""

from __future__ import annotations

import subprocess

import pytest

CONTAINER = "part2-postgres"
DB = "part3"


def query(sql: str) -> list[str]:
    """Run SQL and return stripped result lines."""
    result = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "psql", "-U", "postgres", "-d", DB, "-At", "-c", sql],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return [line for line in result.stdout.strip().splitlines() if line]


def scalar(sql: str) -> str:
    rows = query(sql)
    return rows[0] if rows else ""


def database_available() -> bool:
    try:
        subprocess.run(["docker", "exec", CONTAINER, "pg_isready", "-U", "postgres"],
                       capture_output=True, timeout=15, check=True)
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(
    not database_available(),
    reason=f"PostgreSQL container {CONTAINER} is not available",
)


# --- Part II preservation -------------------------------------------

PART2_TABLES = [
    "account", "account_alias", "billing_account", "account_billing_account",
    "account_admin", "account_admin_assignment", "account_relationship", "account_member",
    "customer", "customer_relationship", "customer_contract_role", "customer_benefit_role",
    "customer_associate_role", "associate", "manager_contract", "account_manager_contract",
    "associate_relationship", "contract", "contract_benefit", "contract_premium",
    "dataset", "data_asset", "geographic_area", "health_indicator",
    "health_observation", "account_geography",
]


@pytest.mark.parametrize("table", PART2_TABLES)
def test_part2_table_still_exists(table):
    """All 26 Part II tables must survive the Part III physical layer."""
    n = scalar(f"SELECT count(*) FROM information_schema.tables "
               f"WHERE table_schema='public' AND table_name='{table}'")
    assert n == "1", f"Part II table {table} is missing"


def test_part2_table_count():
    assert len(PART2_TABLES) == 26


def test_part2_business_constraints_present():
    for name in ["uq_account_business", "uq_manager_contract", "uq_contract_number"]:
        n = scalar(f"SELECT count(*) FROM pg_constraint WHERE conname='{name}'")
        assert n == "1", f"Part II constraint {name} is missing"


# --- Part III objects -----------------------------------------------

PART3_TABLES = [
    "quote", "quote_coverage", "quote_risk_factor", "quote_status_history",
    "payment_authorization", "quote_conversion",
    "ml_run", "document_chunk", "ml_cluster_result", "ml_cluster_summary",
]


@pytest.mark.parametrize("table", PART3_TABLES)
def test_part3_table_exists(table):
    n = scalar(f"SELECT count(*) FROM information_schema.tables "
               f"WHERE table_schema='public' AND table_name='{table}'")
    assert n == "1", f"Part III table {table} is missing"


def test_total_table_count():
    """26 Part II + 6 workflow + 4 ML = 36, plus synthetic performance tables."""
    n = int(scalar("SELECT count(*) FROM information_schema.tables "
                   "WHERE table_schema='public' AND table_type='BASE TABLE' "
                   "AND table_name NOT LIKE 'perf_%'"))
    assert n == 36


PART3_INDEXES = [
    "ix_obs_geo_ind_year", "ix_obs_ind_geo_covering", "ix_acctgeo_geo_type",
    "ix_geo_countyfips_partial", "ix_contract_account_active", "ix_premium_mgr_year",
    "ix_customer_name", "ix_asset_dataset_type", "ix_quote_open_status",
    "ix_quote_customer_date", "ix_conversion_contract", "ix_qsh_quote_time",
    "ix_mlcr_run_cluster", "ix_mlcr_chunk", "ix_chunk_asset_page", "ix_mlrun_dataset_started",
]


@pytest.mark.parametrize("index", PART3_INDEXES)
def test_part3_index_exists(index):
    n = scalar(f"SELECT count(*) FROM pg_indexes WHERE schemaname='public' AND indexname='{index}'")
    assert n == "1", f"Part III index {index} is missing"


def test_partial_indexes_have_predicates():
    """Partial indexes must actually carry a WHERE clause."""
    for index in ["ix_geo_countyfips_partial", "ix_contract_account_active", "ix_quote_open_status"]:
        definition = scalar(f"SELECT indexdef FROM pg_indexes WHERE indexname='{index}'")
        assert " WHERE " in definition, f"{index} is not actually partial"


def test_covering_index_has_include():
    definition = scalar("SELECT indexdef FROM pg_indexes WHERE indexname='ix_obs_ind_geo_covering'")
    assert "INCLUDE" in definition


def test_audit_columns_exist():
    for table in ["account", "customer", "contract"]:
        for column in ["createdat", "updatedat"]:
            n = scalar(f"SELECT count(*) FROM information_schema.columns "
                       f"WHERE table_schema='public' AND table_name='{table}' "
                       f"AND column_name='{column}'")
            assert n == "1", f"{table}.{column} is missing"


# --- Materialized view ----------------------------------------------

def test_materialized_view_exists():
    n = scalar("SELECT count(*) FROM pg_matviews WHERE matviewname='mv_account_regional_health_profile'")
    assert n == "1"


def test_materialized_view_is_populated():
    n = int(scalar("SELECT count(*) FROM MV_ACCOUNT_REGIONAL_HEALTH_PROFILE"))
    assert n > 0, "materialized view is empty; refresh it"


def test_materialized_view_is_in_sync():
    status = scalar("SELECT status FROM V_MV_ARHP_VALIDATION")
    assert status == "IN SYNC", f"materialized view is stale: {status}"


def test_materialized_view_has_unique_index():
    """Required for REFRESH ... CONCURRENTLY."""
    n = scalar("SELECT count(*) FROM pg_indexes "
               "WHERE indexname='ux_mv_arhp_identity'")
    assert n == "1"


# --- Referential integrity ------------------------------------------

ORPHAN_CHECKS = {
    "health_observation -> geographic_area":
        "SELECT count(*) FROM HEALTH_OBSERVATION o LEFT JOIN GEOGRAPHIC_AREA g "
        "ON g.GeographyID=o.GeographyID WHERE g.GeographyID IS NULL",
    "health_observation -> health_indicator":
        "SELECT count(*) FROM HEALTH_OBSERVATION o LEFT JOIN HEALTH_INDICATOR i "
        "ON i.IndicatorID=o.IndicatorID WHERE i.IndicatorID IS NULL",
    "data_asset -> dataset":
        "SELECT count(*) FROM DATA_ASSET a LEFT JOIN DATASET d "
        "ON d.DatasetID=a.DatasetID WHERE d.DatasetID IS NULL",
    "contract -> account":
        "SELECT count(*) FROM CONTRACT c LEFT JOIN ACCOUNT a "
        "ON a.AccountID=c.AccountID WHERE a.AccountID IS NULL",
    "ml_cluster_result -> document_chunk":
        "SELECT count(*) FROM ML_CLUSTER_RESULT r LEFT JOIN DOCUMENT_CHUNK c "
        "ON c.DocumentChunkID=r.DocumentChunkID WHERE c.DocumentChunkID IS NULL",
    "document_chunk -> ds010":
        "SELECT count(*) FROM DOCUMENT_CHUNK c JOIN DATA_ASSET a ON a.AssetID=c.DataAssetID "
        "WHERE a.DatasetID <> 'DS010'",
}


@pytest.mark.parametrize("name,sql", list(ORPHAN_CHECKS.items()))
def test_no_orphans(name, sql):
    assert scalar(sql) == "0", f"orphan rows found: {name}"


# --- ML governance ---------------------------------------------------

def test_ml_run_recorded():
    n = int(scalar("SELECT count(*) FROM ML_RUN WHERE Status='Completed'"))
    assert n >= 1, "no completed ML run recorded"


def test_ml_run_has_seed_and_metrics():
    seed = scalar("SELECT RandomSeed FROM ML_RUN ORDER BY MLRunID LIMIT 1")
    assert seed == "42"
    k = scalar("SELECT MetricsJSON ->> 'selected_k' FROM ML_RUN ORDER BY MLRunID LIMIT 1")
    assert int(k) >= 2


def test_every_chunk_has_a_cluster():
    chunks = int(scalar("SELECT count(*) FROM DOCUMENT_CHUNK"))
    assigned = int(scalar("SELECT count(DISTINCT DocumentChunkID) FROM ML_CLUSTER_RESULT"))
    assert chunks == assigned, f"{chunks - assigned} chunks have no cluster assignment"


def test_cluster_summary_matches_results():
    summary = int(scalar("SELECT count(*) FROM ML_CLUSTER_SUMMARY"))
    distinct = int(scalar("SELECT count(DISTINCT ClusterID) FROM ML_CLUSTER_RESULT"))
    assert summary == distinct


def test_review_flag_requires_reviewer():
    """The governance constraint must be enforced, not merely documented."""
    bad = scalar("SELECT count(*) FROM ML_CLUSTER_SUMMARY "
                 "WHERE HumanReviewed = TRUE AND (ReviewedBy IS NULL OR ReviewedAt IS NULL)")
    assert bad == "0"


# --- Roles ------------------------------------------------------------

@pytest.mark.parametrize("role", ["insurance_app", "insurance_analyst", "ml_writer", "data_loader"])
def test_role_exists(role):
    assert scalar(f"SELECT count(*) FROM pg_roles WHERE rolname='{role}'") == "1"


def test_analyst_cannot_read_ssn():
    """Column-level privilege: the analyst role must not hold SSN_TIN access."""
    n = scalar("SELECT count(*) FROM information_schema.column_privileges "
               "WHERE grantee='insurance_analyst' AND table_name='customer' "
               "AND column_name='ssn_tin'")
    assert n == "0", "insurance_analyst should not have access to CUSTOMER.SSN_TIN"
