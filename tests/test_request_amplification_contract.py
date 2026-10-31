"""Deterministic request-amplification and CPU-attribution contract (issue #4273).

This module pins the parts of the #4273 acceptance criteria that are verifiable
inside the existing Python test setup without the production-shaped replay lab
(#4277) or the once-per-session identity cutover (#4275):

- a deliberately long wait is charged to wall time, never to process CPU, so the
  historical ``process_time_ms`` label cannot silently become a CPU claim;
- N protected requests from one authenticated session never perform more than
  one identity lookup each, which is the current one-per-request baseline that
  the zero-repeat assertion will tighten after #4275;
- per-route counters count completed invocations once per request, aggregate by
  route template, and are never derived from log lines.

The isolated cold/warm process-CPU suite, the controlled parallel view-load
scenario, and the browser request-fan-out contract are replay-lab deliverables
(#4277). The documented method, the ranking formula, the manual daily Active CPU
comparison step, and the still-unverified criteria are recorded in
``docs/REQUEST_AMPLIFICATION_CONTRACT.md``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from app.middleware.request_logging import add_request_logging_middleware
from app.performance_diagnostics import (
    begin_request_diagnostics,
    end_request_diagnostics,
    get_request_diagnostics,
    identity_database_query_scope,
    record_database_query,
)
from app.traffic_metrics import reset_traffic_counters_for_tests, traffic_snapshot

_WAIT_SECONDS = 0.5
_CPU_SLACK_MS = 300.0


def _performance_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """Return structured performance-warning records from the request logger."""
    return [
        record
        for record in caplog.records
        if record.name == "app.middleware.request_logging"
        and record.getMessage().startswith("Performance warning:")
    ]


@pytest.fixture(autouse=True)
def _clean_traffic_counters() -> Iterator[None]:
    """Keep process-local counters isolated between contract tests."""
    reset_traffic_counters_for_tests()
    yield
    reset_traffic_counters_for_tests()


@pytest.mark.asyncio
async def test_five_hundred_millisecond_wait_is_wall_time_not_cpu(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A 500 ms I/O wait must show up as wall time while CPU stays near zero.

    This is the local control for the replay lab's 500 ms DB-delay experiment:
    a delay that performs no work must not be attributed to Python CPU, which is
    exactly the distinction the historical ``process_time_ms`` name obscured.
    """
    monkeypatch.setenv("SLOW_REQUEST_THRESHOLD_MS", "1")
    app = FastAPI()
    add_request_logging_middleware(app, "test")

    @app.get("/delayed")
    async def delayed_route() -> dict[str, str]:
        """Return after a 500 ms wait that consumes no measurable CPU."""
        await asyncio.sleep(_WAIT_SECONDS)
        return {"status": "ok"}

    caplog.set_level(logging.WARNING, logger="app.middleware.request_logging")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/delayed")
    assert response.status_code == 200
    assert response.headers["X-App-Auth-DB-Queries"] == "0"

    records = _performance_warnings(caplog)
    assert len(records) == 1
    extras = records[0].__dict__
    wall_ms = extras["process_time_ms"]
    cpu_ms = extras["cpu_time_ms"]
    assert extras["identity_database_queries"] == 0
    assert extras["identity_database_time_ms"] == 0.0

    # The wall clock saw the full wait; the process CPU did not do that work.
    assert wall_ms >= _WAIT_SECONDS * 1000 * 0.9
    assert cpu_ms < _CPU_SLACK_MS
    assert cpu_ms < wall_ms * 0.75


@contextmanager
def _captured_selects(db_engine: AsyncEngine) -> Iterator[list[str]]:
    """Yield a list that records SELECT statements executed on the engine."""
    select_statements: list[str] = []

    def _capture(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            select_statements.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        yield select_statements
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _capture)


@pytest.mark.asyncio
async def test_repeated_protected_requests_do_not_multiply_identity_lookups(
    auth_client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """Each ordinary protected request runs at most one identity lookup.

    The current pre-#4275 baseline is exactly one joined user/revocation lookup
    per authenticated request, so N requests mean N identity SELECTs. The
    contract is written as an upper bound: when #4275 validates identity without
    a SQL round trip, zero per request still satisfies it, while a regression
    that adds a second lookup per request fails immediately.
    """
    protected_requests = 5
    per_request_selects: list[list[str]] = []

    for _ in range(protected_requests):
        with _captured_selects(db_engine) as statements:
            response = await auth_client.get("/api/v1/auth/me")
        assert response.status_code == 200
        # Header counters come from the app engine's SQLAlchemy events, while
        # the test overrides ``get_db`` with a session on the test engine. Only
        # the subset invariant holds on both sides; the exact identity count is
        # covered by the explicit-scope test below.
        auth_queries = int(response.headers["X-App-Auth-DB-Queries"])
        total_queries = int(response.headers["X-App-DB-Queries"])
        assert 0 <= auth_queries <= total_queries
        assert auth_queries <= len(statements)
        per_request_selects.append(statements)

    for statements in per_request_selects:
        assert len(statements) <= 1, statements
        for statement in statements:
            assert "join" in statement.lower(), statement

    total_identity_selects = sum(len(statements) for statements in per_request_selects)
    assert total_identity_selects <= protected_requests


def test_identity_query_scope_separates_identity_from_business_sql() -> None:
    """Identity SQL is a counted subset of the request's total SQL.

    The middleware cannot infer which statements authenticate the caller, so
    ``get_current_user()`` opens an explicit scope around its repository call.
    Business statements outside that scope must contribute to the total only.
    """
    token = begin_request_diagnostics()
    try:
        record_database_query(3.0)
        with identity_database_query_scope():
            record_database_query(5.0)
            with identity_database_query_scope():
                record_database_query(2.0)
        record_database_query(4.0)
        diagnostics = get_request_diagnostics()
    finally:
        end_request_diagnostics(token)

    assert diagnostics.database_queries == 4
    assert diagnostics.database_time_ms == 14.0
    assert diagnostics.identity_database_queries == 2
    assert diagnostics.identity_database_time_ms == 7.0


@pytest.mark.asyncio
async def test_repeated_view_requests_count_invocations_once_each(
    auth_client: AsyncClient,
) -> None:
    """Route counters count completed invocations, not log lines.

    A successful warm request usually emits no runtime log line, so log-event
    counts cannot stand in for traffic. Three completed requests to one route
    must therefore produce exactly three counted invocations under the route
    template.
    """
    invocations = 3
    for _ in range(invocations):
        response = await auth_client.get("/api/v1/auth/me")
        assert response.status_code == 200

    counts = {
        (counter.method, counter.route, counter.status_class): counter.count
        for counter in traffic_snapshot().counters
    }
    assert counts.get(("GET", "/api/v1/auth/me", "2xx")) == invocations


@pytest.mark.asyncio
async def test_route_counters_aggregate_parameterized_paths_by_template(
    auth_client: AsyncClient,
) -> None:
    """Different resource ids collapse into one template bucket, not raw paths."""
    for thread_id in (1, 2):
        response = await auth_client.get(f"/api/v1/threads/{thread_id}")
        assert response.status_code in (200, 404)

    counts = {
        (counter.method, counter.route, counter.status_class): counter.count
        for counter in traffic_snapshot().counters
    }
    template_counts = [
        count
        for (method, route, _), count in counts.items()
        if method == "GET" and route == "/api/v1/threads/{thread_id}"
    ]
    assert sum(template_counts) == 2
    assert not any(route in {"/api/v1/threads/1", "/api/v1/threads/2"} for _, route, _ in counts)
