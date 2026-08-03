"""Phase instrumentation and statement-count regressions for session reads.

Issue #700: structured phase/query-count instrumentation was the final
executable slice deferred by the merged read-pipeline PR. These tests prove:

- ``get_current_session()`` records named phases and exact per-phase SQL
  statement counts through the request diagnostics context;
- ``list_sessions()`` records bounded History phases;
- the middleware surfaces phase timings and query counts in the
  ``Server-Timing`` response header and the structured request log.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Event, Issue, Thread, User
from app.models import Session as SessionModel
from app.performance_diagnostics import get_request_diagnostics, record_phase
from app.database import install_database_instrumentation


@pytest.fixture(autouse=True)
def _instrument_engine(db_engine: AsyncEngine) -> None:
    """Attach the query-count listeners to the test engine."""
    install_database_instrumentation(db_engine)


def _parse_server_timing(header: str) -> dict[str, int]:
    """Parse ``name;dur=..;desc="N queries"`` entries into name -> query count."""
    counts: dict[str, int] = {}
    for metric in header.split(","):
        metric = metric.strip()
        if not metric:
            continue
        parts = [p.strip() for p in metric.split(";")]
        name = parts[0]
        for part in parts[1:]:
            if part.startswith('desc="') and part.endswith(' queries"'):
                counts[name] = int(part[6:-9])
    return counts


async def _seed_current_session(
    async_db: AsyncSession, user: User, *, issues_remaining: int = 2
) -> SessionModel:
    """Seed an active session with a rolled migrated thread and return it."""
    session = SessionModel(start_die=10, user_id=user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Phase Comic",
        format="Comic",
        issues_remaining=issues_remaining,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=4,
        reading_progress="in_progress",
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    for i in range(1, 5):
        async_db.add(
            Issue(
                thread_id=thread.id,
                issue_number=str(i),
                status="read" if i < 3 else "unread",
                position=i,
            )
        )
    await async_db.commit()

    issue_result = await async_db.execute(
        __import__("sqlalchemy").select(Issue).where(
            Issue.thread_id == thread.id, Issue.issue_number == "3"
        )
    )
    next_issue = issue_result.scalar_one()
    thread.next_unread_issue_id = next_issue.id
    await async_db.commit()

    async_db.add(
        Event(
            type="roll",
            die=10,
            result=1,
            selected_thread_id=thread.id,
            selection_method="random",
            session_id=session.id,
            thread_id=thread.id,
        )
    )
    await async_db.commit()
    return session


def _statement_recorder() -> tuple[list[str], object]:
    """Return a statement list and a SQLAlchemy before_cursor_execute listener."""
    statements: list[str] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    return statements, record_statement


@pytest.mark.asyncio
async def test_current_session_phase_query_counts_match_statement_counts(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
) -> None:
    """Per-phase query counts equal the real SQL statement counts in the path."""
    await _seed_current_session(async_db, default_user)

    statements, listener = _statement_recorder()
    sa_event.listen(db_engine.sync_engine, "before_cursor_execute", listener)
    try:
        response = await auth_client.get("/api/sessions/current/")
    finally:
        sa_event.remove(db_engine.sync_engine, "before_cursor_execute", listener)

    assert response.status_code == 200
    assert "server-timing" in response.headers

    app_statements = [
        s
        for s in statements
        if "savepoint" not in s.lower()
        and "revoked_tokens" not in s.lower()
        and "from users" not in s.lower()
    ]
    timing_counts = _parse_server_timing(response.headers["server-timing"])

    for name in ("candidate_selection", "session_refresh", "active_thread"):
        assert name in timing_counts, f"Missing phase {name!r} in {timing_counts}"

    expected_total = sum(
        count
        for name, count in timing_counts.items()
        if name
        in (
            "candidate_selection",
            "session_refresh",
            "active_thread",
            "snapshot_count",
            "snoozed_threads",
            "ladder_path",
            "current_die",
        )
    )
    assert expected_total == len(app_statements), (
        f"Phase query counts ({expected_total}) must match real statements "
        f"({len(app_statements)}): {app_statements}"
    )


@pytest.mark.asyncio
async def test_current_session_records_expected_phases_in_diagnostics(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
) -> None:
    """The diagnostics context exposes named phases for the current-session path."""
    await _seed_current_session(async_db, default_user)

    response = await auth_client.get("/api/sessions/current/")
    assert response.status_code == 200
    assert "server-timing" in response.headers

    timing_counts = _parse_server_timing(response.headers["server-timing"])
    expected_phases = {
        "candidate_selection",
        "session_refresh",
        "active_thread",
        "snapshot_count",
        "ladder_path",
        "current_die",
    }
    assert expected_phases.issubset(timing_counts), (
        f"Expected phases {expected_phases}, got {set(timing_counts)}"
    )
    assert timing_counts["candidate_selection"] == 1
    assert timing_counts["snapshot_count"] == 1
    assert timing_counts["ladder_path"] == 1
    assert timing_counts["current_die"] == 2
    assert timing_counts["snoozed_threads"] == 0


@pytest.mark.asyncio
async def test_current_session_phase_durations_are_nonnegative(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Each recorded phase carries a real nonnegative wall-clock duration."""
    await _seed_current_session(async_db, default_user)

    response = await auth_client.get("/api/sessions/current/")
    assert response.status_code == 200
    server_timing = response.headers["server-timing"]

    for metric in server_timing.split(","):
        parts = [p.strip() for p in metric.split(";")]
        name = parts[0]
        if name in {
            "candidate_selection",
            "session_refresh",
            "active_thread",
            "snapshot_count",
            "snoozed_threads",
            "ladder_path",
            "current_die",
        }:
            duration_part = next(p for p in parts if p.startswith("dur="))
            assert float(duration_part[4:]) >= 0.0, f"Phase {name} has negative duration"


@pytest.mark.asyncio
async def test_record_phase_accumulates_duration_and_queries() -> None:
    """``record_phase`` records elapsed wall-clock time on the active context."""
    import asyncio

    from app.performance_diagnostics import begin_request_diagnostics, end_request_diagnostics

    token = begin_request_diagnostics()
    try:
        async with record_phase("probe_phase"):
            await asyncio.sleep(0.01)
    finally:
        diagnostics = get_request_diagnostics()
        end_request_diagnostics(token)

    assert "probe_phase" in diagnostics.phases
    assert diagnostics.phases["probe_phase"].duration_ms >= 10.0
    assert diagnostics.phases["probe_phase"].query_count == 0


@pytest.mark.asyncio
async def test_history_records_bounded_phases(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """History page records bounded read phases in the Server-Timing header."""
    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.commit()

    response = await auth_client.get("/api/sessions/?page_size=10")
    assert response.status_code == 200

    timing_counts = _parse_server_timing(response.headers["server-timing"])
    for name in ("history_page", "history_events", "history_snapshot_counts"):
        assert name in timing_counts, f"Missing History phase {name!r} in {timing_counts}"
    assert timing_counts["history_page"] == 1
    assert timing_counts["history_events"] == 1
    assert timing_counts["history_snapshot_counts"] == 1


@pytest.mark.asyncio
async def test_structured_log_exposes_phase_timings(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Structured slow-request logs include per-phase timing and query counts."""
    monkeypatch.setenv("SLOW_REQUEST_THRESHOLD_MS", "1")
    await _seed_current_session(async_db, default_user)

    caplog.set_level(logging.WARNING, logger="app.middleware.request_logging")
    await auth_client.get("/api/sessions/current/")

    slow_records = [
        record
        for record in caplog.records
        if record.name == "app.middleware.request_logging"
        and record.getMessage().startswith("Slow HTTP request:")
    ]
    assert len(slow_records) == 1
    extra = slow_records[0].__dict__
    assert "phase_timings_ms" in extra
    assert "phase_query_counts" in extra
    assert extra["phase_query_counts"]["candidate_selection"] == 1
    assert "active_thread" in extra["phase_timings_ms"]
