"""Database engine, session management, and query instrumentation.

One Engine is created per process. It owns the connection pool, so a
request pays no connection setup cost. Sessions are short-lived and
scoped to a unit of work: a request, a job step, or a test.

The module also carries a small query counter used by the optimization
measurements in part4/evidence/query_performance.csv. Counting statements
at the driver level is the only way to see an N+1 pattern honestly;
reading the ORM code is not enough, because whether a relationship
triggers a second SELECT depends on the loader strategy in force at
runtime.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import CONFIG

log = logging.getLogger("part4.db")

ENGINE: Engine = create_engine(
    CONFIG.db_url,
    pool_size=CONFIG.pool_size,
    max_overflow=CONFIG.max_overflow,
    # Verifies a pooled connection before handing it out. Without this a
    # container restart turns every pooled connection into a 500.
    pool_pre_ping=CONFIG.pool_pre_ping,
    pool_recycle=1800,
    echo=CONFIG.echo_sql,
    future=True,
)

SessionFactory = sessionmaker(
    bind=ENGINE,
    autoflush=False,
    # Objects stay usable after commit, so a service can return an ORM
    # object and a template can still read its attributes.
    expire_on_commit=False,
    future=True,
)


# ---------------------------------------------------------------------
# Query instrumentation
# ---------------------------------------------------------------------
@dataclass
class QueryTrace:
    """Statements captured inside one measurement window."""

    statements: list[str] = field(default_factory=list)
    total_seconds: float = 0.0

    @property
    def count(self) -> int:
        return len(self.statements)


_local = threading.local()


@event.listens_for(ENGINE, "before_cursor_execute")
def _before(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
    trace = getattr(_local, "trace", None)
    if trace is not None:
        conn.info["_p4_started"] = time.perf_counter()


@event.listens_for(ENGINE, "after_cursor_execute")
def _after(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
    trace = getattr(_local, "trace", None)
    if trace is not None:
        started = conn.info.pop("_p4_started", None)
        if started is not None:
            trace.total_seconds += time.perf_counter() - started
        trace.statements.append(" ".join(statement.split()))


@contextmanager
def count_queries() -> Iterator[QueryTrace]:
    """Capture every SQL statement emitted inside the block.

    Used by the optimization tests to record query counts before and
    after a loader-strategy change.
    """
    trace = QueryTrace()
    previous = getattr(_local, "trace", None)
    _local.trace = trace
    try:
        yield trace
    finally:
        _local.trace = previous


# ---------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------
@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional scope around a unit of work.

    Commit on success, rollback on any exception, close always. Every
    business workflow in Part IV runs inside one of these blocks, which
    is what makes quote creation, status transition, and policy issuance
    atomic rather than a sequence of independent writes.
    """
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def read_session() -> Iterator[Session]:
    """Read-only scope for request rendering.

    close() returns the connection to the pool and detaches the loaded
    objects, leaving the attributes that were already fetched readable by
    a template. An explicit rollback() here would instead mark every
    attribute expired, and the first attribute a template touched would
    raise DetachedInstanceError.

    The consequence is that a route must eagerly load everything its
    template reads. That is the intended discipline: it is also what
    keeps the page's query count bounded.
    """
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()


def check_connection() -> tuple[bool, str]:
    """Return (ok, message) describing database availability.

    The dashboard and the demo script both call this so an unavailable
    database produces a clear message instead of a stack trace.
    """
    from sqlalchemy import text

    try:
        with ENGINE.connect() as conn:
            version = conn.execute(text("SHOW server_version")).scalar_one()
            database = conn.execute(text("SELECT current_database()")).scalar_one()
        return True, f"PostgreSQL {version} / {database}"
    except Exception as exc:  # noqa: BLE001 - surfaced to the user as text
        log.error("Database unavailable: %s", exc)
        return False, str(exc).splitlines()[0]
