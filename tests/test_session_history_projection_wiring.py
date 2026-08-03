"""Endpoint-level regression coverage for the linear History event projection.

These tests prove ``list_sessions()`` preserves the exact History response
contract when it assembles summaries from the single ordered event read
produced by ``project_session_history_events()``.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Event, Thread, User
from app.models import Session as SessionModel


async def _commit_all(async_db: AsyncSession) -> None:
    await async_db.flush()
    await async_db.commit()


def _roll_event(
    session: SessionModel,
    thread: Thread,
    *,
    timestamp: int,
    thread_id: int | None = None,
) -> Event:
    """Build a roll event for a fixed deterministic wall clock."""
    return Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        thread_id=thread_id,
        die=session.start_die,
        result=timestamp,
        selection_method="random",
        timestamp=datetime(2026, 8, 2, 12, 0, timestamp, tzinfo=UTC),
    )


def _die_event(
    session: SessionModel,
    thread: Thread,
    *,
    timestamp: int,
    die_after: int,
) -> Event:
    """Build a rate/snooze die-transition event at a fixed wall clock."""
    return Event(
        type="rate",
        session_id=session.id,
        thread_id=thread.id,
        die_after=die_after,
        timestamp=datetime(2026, 8, 2, 12, 0, timestamp, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_history_ladder_is_chronological_and_current_die_uses_latest(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Ladder order stays chronological and current_die uses the newest event."""
    thread = Thread(
        title="Ladder Comic",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    async_db.add(thread)
    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.flush()
    async_db.add_all(
        [
            _die_event(session, thread, timestamp=1, die_after=8),
            _die_event(session, thread, timestamp=2, die_after=12),
            _die_event(session, thread, timestamp=3, die_after=10),
        ]
    )
    await _commit_all(async_db)

    response = await auth_client.get("/api/sessions/")
    assert response.status_code == 200
    item = next(s for s in response.json()["sessions"] if s["id"] == session.id)

    assert item["ladder_path"] == "6 → 8 → 12 → 10"
    assert item["current_die"] == 10
    assert item["start_die"] == 6


@pytest.mark.asyncio
async def test_history_manual_die_overrides_event_derived_die(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """A manual die takes precedence over event-derived current die."""
    thread = Thread(
        title="Manual Die Comic",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    async_db.add(thread)
    session = SessionModel(
        start_die=6,
        manual_die=20,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    async_db.add(session)
    await async_db.flush()
    async_db.add(_die_event(session, thread, timestamp=1, die_after=8))
    await _commit_all(async_db)

    response = await auth_client.get("/api/sessions/")
    assert response.status_code == 200
    item = next(s for s in response.json()["sessions"] if s["id"] == session.id)

    assert item["current_die"] == 20
    assert item["manual_die"] == 20
    assert item["ladder_path"] == "6 → 8"


@pytest.mark.asyncio
async def test_history_no_die_events_falls_back_to_start_die(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Sessions without die events fall back to the start die for ladder and die."""
    session = SessionModel(start_die=10, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await _commit_all(async_db)

    response = await auth_client.get("/api/sessions/")
    assert response.status_code == 200
    item = next(s for s in response.json()["sessions"] if s["id"] == session.id)

    assert item["ladder_path"] == "10"
    assert item["current_die"] == 10


@pytest.mark.asyncio
async def test_history_latest_roll_wins_when_multiple_rolls_exist(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Latest roll selection uses event order and returns the newest thread."""
    thread_a = Thread(
        title="First Comic",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    thread_b = Thread(
        title="Second Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=2,
        user_id=default_user.id,
    )
    async_db.add_all([thread_a, thread_b])
    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.flush()
    async_db.add_all(
        [
            _roll_event(session, thread_a, timestamp=1),
            _roll_event(session, thread_b, timestamp=2),
        ]
    )
    await _commit_all(async_db)

    response = await auth_client.get("/api/sessions/")
    assert response.status_code == 200
    item = next(s for s in response.json()["sessions"] if s["id"] == session.id)

    assert item["active_thread"] is not None
    assert item["active_thread"]["title"] == "Second Comic"
    assert item["last_rolled_result"] == 2


@pytest.mark.asyncio
async def test_history_deleted_thread_yields_null_active_thread(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Rolls referencing a deleted thread produce active_thread=None."""
    thread = Thread(
        title="Doomed Comic",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    async_db.add(thread)
    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.flush()
    await _commit_all(async_db)

    async_db.add(_roll_event(session, thread, timestamp=1, thread_id=None))
    await _commit_all(async_db)

    await async_db.delete(thread)
    await _commit_all(async_db)
    response = await auth_client.get("/api/sessions/")
    assert response.status_code == 200
    item = next(s for s in response.json()["sessions"] if s["id"] == session.id)

    assert item["active_thread"] is None
    assert item["last_rolled_result"] is None


@pytest.mark.asyncio
async def test_history_event_reads_do_not_grow_per_session(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
) -> None:
    """The History page performs one events read regardless of page size."""
    for i in range(5):
        thread = Thread(
            title=f"Comic {i}",
            format="Comic",
            issues_remaining=10,
            queue_position=i + 1,
            user_id=default_user.id,
        )
        async_db.add(thread)
        session = SessionModel(
            start_die=6,
            user_id=default_user.id,
            started_at=datetime(2026, 8, 2, 12, 0, i, tzinfo=UTC),
        )
        async_db.add(session)
        await _commit_all(async_db)
        async_db.add(_roll_event(session, thread, timestamp=i))
        async_db.add(_die_event(session, thread, timestamp=i, die_after=8 + i))
        await _commit_all(async_db)

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

    sa_event.listen(db_engine.sync_engine, "before_cursor_execute", record_statement)
    try:
        response = await auth_client.get("/api/sessions/?page_size=50")
    finally:
        sa_event.remove(db_engine.sync_engine, "before_cursor_execute", record_statement)

    assert response.status_code == 200
    assert len(response.json()["sessions"]) == 5

    event_reads = [s for s in statements if "from events" in s.lower()]
    assert len(event_reads) == 1, (
        f"Expected a single events read, got {len(event_reads)}: {event_reads}"
    )


@pytest.mark.asyncio
async def test_history_pagination_preserves_ordering_and_tokens(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Cursor pages keep reverse-chronological ordering and stable tokens."""
    for i in range(5):
        session = SessionModel(
            start_die=6,
            user_id=default_user.id,
            started_at=datetime(2026, 8, 2, 12, 0, 50 - i, tzinfo=UTC),
        )
        async_db.add(session)
        await async_db.flush()
    await _commit_all(async_db)

    first_page = await auth_client.get("/api/sessions/?page_size=2")
    assert first_page.status_code == 200
    first_data = first_page.json()
    first_sessions = first_data["sessions"]
    assert len(first_sessions) == 2
    assert [s["started_at"] for s in first_sessions] == sorted(
        (s["started_at"] for s in first_sessions), reverse=True
    ), "Sessions must be newest-first by started_at"

    next_token = first_data.get("next_page_token")
    assert next_token is not None

    second_page = await auth_client.get(
        "/api/sessions/", params={"page_size": 2, "page_token": next_token}
    )
    assert second_page.status_code == 200
    second_data = second_page.json()
    second_sessions = second_data["sessions"]
    assert len(second_sessions) == 2
    assert [s["started_at"] for s in second_sessions] == sorted(
        (s["started_at"] for s in second_sessions), reverse=True
    ), "Second page continues newest-first ordering"

    assert {s["id"] for s in first_sessions}.isdisjoint({s["id"] for s in second_sessions})
    assert all(first_sessions[-1]["started_at"] > s["started_at"] for s in second_sessions), (
        "First page must be strictly newer than the second page"
    )

    third_page = await auth_client.get(
        "/api/sessions/", params={"page_size": 2, "page_token": second_data["next_page_token"]}
    )
    assert third_page.status_code == 200
    third_data = third_page.json()
    assert len(third_data["sessions"]) == 1
    assert third_data["next_page_token"] is None


@pytest.mark.asyncio
async def test_history_duplicate_timestamps_break_ties_by_event_id(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Latest die selection uses event ID to break equal timestamp ties."""
    thread = Thread(
        title="Tie Comic",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        user_id=default_user.id,
    )
    async_db.add(thread)
    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.flush()

    first = _die_event(session, thread, timestamp=1, die_after=8)
    second = _die_event(session, thread, timestamp=1, die_after=12)
    async_db.add_all([first, second])
    await async_db.flush()

    first.id, second.id = 100, 101
    await _commit_all(async_db)

    response = await auth_client.get("/api/sessions/")
    assert response.status_code == 200
    item = next(s for s in response.json()["sessions"] if s["id"] == session.id)

    assert item["current_die"] == 12
    assert item["ladder_path"] == "6 → 8 → 12"


@pytest.mark.asyncio
async def test_history_active_thread_metadata_loads_in_bulk(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
) -> None:
    """Migrated unread counts and issue numbers are bulk-loaded, not per-thread."""
    from app.models import Issue

    migrated = Thread(
        title="Migrated Comic",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        user_id=default_user.id,
        total_issues=5,
        reading_progress="in_progress",
    )
    unmigrated = Thread(
        title="Legacy Comic",
        format="Comic",
        issues_remaining=42,
        queue_position=2,
        user_id=default_user.id,
    )
    async_db.add_all([migrated, unmigrated])
    await async_db.flush()
    session_a = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    session_b = SessionModel(start_die=8, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add_all([session_a, session_b])
    await async_db.flush()

    for i in range(1, 6):
        async_db.add(
            Issue(
                thread_id=migrated.id,
                issue_number=str(i),
                position=i,
                status="read" if i <= 3 else "unread",
            )
        )
    await async_db.flush()
    async_db.add_all(
        [
            _roll_event(session_a, migrated, timestamp=1),
            _roll_event(session_b, unmigrated, timestamp=1),
        ]
    )
    await _commit_all(async_db)

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

    sa_event.listen(db_engine.sync_engine, "before_cursor_execute", record_statement)
    try:
        response = await auth_client.get("/api/sessions/")
    finally:
        sa_event.remove(db_engine.sync_engine, "before_cursor_execute", record_statement)

    assert response.status_code == 200
    sessions = {s["id"]: s for s in response.json()["sessions"]}

    migrated_active = sessions[session_a.id]["active_thread"]
    assert migrated_active is not None
    assert migrated_active["title"] == "Migrated Comic"
    assert migrated_active["issues_remaining"] == 2
    assert migrated_active["total_issues"] == 5

    unmigrated_active = sessions[session_b.id]["active_thread"]
    assert unmigrated_active is not None
    assert unmigrated_active["title"] == "Legacy Comic"
    assert unmigrated_active["issues_remaining"] == 42

    issue_reads = [s for s in statements if "from issues" in s.lower()]
    assert len(issue_reads) <= 2, (
        f"Expected bounded issue reads, got {len(issue_reads)}: {issue_reads}"
    )


@pytest.mark.asyncio
async def test_history_missing_next_issue_yields_null_issue_metadata(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """A dangling next_unread_issue_id produces null issue fields, not an error."""
    from app.models import Issue

    migrated = Thread(
        title="Broken Reference Comic",
        format="Comic",
        issues_remaining=3,
        queue_position=1,
        user_id=default_user.id,
        total_issues=5,
        reading_progress="in_progress",
    )
    async_db.add(migrated)
    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.flush()

    issues = [
        Issue(
            thread_id=migrated.id,
            issue_number=str(i),
            position=i,
            status="read" if i <= 3 else "unread",
        )
        for i in range(1, 6)
    ]
    async_db.add_all(issues)
    await async_db.flush()
    migrated.next_unread_issue_id = issues[0].id
    await _commit_all(async_db)

    await async_db.delete(issues[0])
    await _commit_all(async_db)

    async_db.add(_roll_event(session, migrated, timestamp=1))
    await _commit_all(async_db)

    response = await auth_client.get("/api/sessions/")
    assert response.status_code == 200
    item = next(s for s in response.json()["sessions"] if s["id"] == session.id)

    assert item["active_thread"] is not None
    assert item["active_thread"]["issues_remaining"] == 2
    assert item["active_thread"]["issue_id"] is None
    assert item["active_thread"]["issue_number"] is None
    assert item["active_thread"]["next_issue_id"] is None
    assert item["active_thread"]["next_issue_number"] is None


@pytest.mark.asyncio
async def test_history_issue_reads_stay_bounded_across_page_sizes(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
) -> None:
    """Issue metadata reads stay bounded as the History page grows."""
    from app.models import Issue

    for i in range(10):
        migrated = Thread(
            title=f"Bulk Comic {i}",
            format="Comic",
            issues_remaining=0,
            queue_position=i + 1,
            user_id=default_user.id,
            total_issues=5,
            reading_progress="in_progress",
        )
        async_db.add(migrated)
        session = SessionModel(
            start_die=6,
            user_id=default_user.id,
            started_at=datetime(2026, 8, 2, 12, 1, i, tzinfo=UTC),
        )
        async_db.add(session)
        await _commit_all(async_db)
        for j in range(1, 6):
            async_db.add(
                Issue(
                    thread_id=migrated.id,
                    issue_number=str(j),
                    position=j,
                    status="unread" if j <= 2 else "read",
                )
            )
        await _commit_all(async_db)
        async_db.add(_roll_event(session, migrated, timestamp=i))
        await _commit_all(async_db)

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

    sa_event.listen(db_engine.sync_engine, "before_cursor_execute", record_statement)
    try:
        response = await auth_client.get("/api/sessions/?page_size=200")
    finally:
        sa_event.remove(db_engine.sync_engine, "before_cursor_execute", record_statement)

    assert response.status_code == 200
    sessions = response.json()["sessions"]
    assert len(sessions) == 10

    issue_reads = [s for s in statements if "from issues" in s.lower()]
    assert len(issue_reads) <= 2, (
        f"Expected bounded issue reads, got {len(issue_reads)}: {issue_reads}"
    )

    active_threads = [s["active_thread"] for s in sessions]
    assert all(t is not None and t["issues_remaining"] == 2 for t in active_threads)


@pytest.mark.asyncio
async def test_history_migrated_zero_unread_returns_zero_not_stored_counter(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """A migrated thread with no unread issues reports 0, not a stale counter."""
    from app.models import Issue

    migrated = Thread(
        title="All Read Comic",
        format="Comic",
        issues_remaining=99,
        queue_position=1,
        user_id=default_user.id,
        total_issues=5,
        reading_progress="in_progress",
    )
    async_db.add(migrated)
    session = SessionModel(start_die=6, user_id=default_user.id, started_at=datetime.now(UTC))
    async_db.add(session)
    await async_db.flush()

    for i in range(1, 6):
        async_db.add(
            Issue(
                thread_id=migrated.id,
                issue_number=str(i),
                position=i,
                status="read",
            )
        )
    await async_db.flush()
    async_db.add(_roll_event(session, migrated, timestamp=1))
    await _commit_all(async_db)

    response = await auth_client.get("/api/sessions/")
    assert response.status_code == 200
    item = next(s for s in response.json()["sessions"] if s["id"] == session.id)

    assert item["active_thread"] is not None
    assert item["active_thread"]["issues_remaining"] == 0


@pytest.mark.asyncio
async def test_current_session_selects_newest_active_candidate(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Current-session selection uses the newest open candidate and stays active."""
    now = datetime.now(UTC)
    open_sessions = [
        SessionModel(start_die=6, user_id=default_user.id, started_at=now),
        SessionModel(start_die=8, user_id=default_user.id, started_at=now),
        SessionModel(
            start_die=10,
            user_id=default_user.id,
            started_at=now - timedelta(hours=2),
            ended_at=now - timedelta(hours=1),
        ),
    ]
    async_db.add_all(open_sessions)
    await _commit_all(async_db)

    response = await auth_client.get("/api/sessions/current/")
    assert response.status_code == 200
    data = response.json()
    assert data["start_die"] in {6, 8}, "Must select one of the active open sessions"


@pytest.mark.asyncio
async def test_current_session_candidate_read_is_bounded(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
) -> None:
    """Current-session selection reads at most one candidate session row."""
    now = datetime.now(UTC)
    for i in range(10):
        async_db.add(
            SessionModel(
                start_die=6,
                user_id=default_user.id,
                started_at=now - timedelta(minutes=i),
            )
        )
    await _commit_all(async_db)

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

    sa_event.listen(db_engine.sync_engine, "before_cursor_execute", record_statement)
    try:
        response = await auth_client.get("/api/sessions/current/")
    finally:
        sa_event.remove(db_engine.sync_engine, "before_cursor_execute", record_statement)

    assert response.status_code == 200
    assert response.json()["start_die"] == 6

    session_candidate_reads = [
        s for s in statements if "from sessions" in s.lower() and "order by" in s.lower()
    ]
    assert len(session_candidate_reads) == 1, (
        f"Expected one bounded candidate read, got {len(session_candidate_reads)}: "
        f"{session_candidate_reads}"
    )
