"""Tests for rating an issue directly from its Thread row (issue #3581)."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Issue, ReadingSession, Snapshot, Thread, User


async def _create_issue_tracked_thread(
    async_db: AsyncSession,
    user_id: int,
    *,
    issue_numbers: tuple[str, ...] = ("1", "2", "3"),
    next_unread_number: str = "1",
) -> tuple[Thread, dict[str, Issue]]:
    """Create an issue-tracked thread with one unread Issue row per number."""
    now = datetime.now(UTC)
    thread = Thread(
        title="Direct Rating",
        format="Comic",
        issues_remaining=len(issue_numbers),
        total_issues=len(issue_numbers),
        queue_position=1,
        status="active",
        reading_progress="in_progress",
        user_id=user_id,
        last_activity_at=now,
    )
    async_db.add(thread)
    await async_db.flush()

    issues: dict[str, Issue] = {}
    for position, issue_number in enumerate(issue_numbers, start=1):
        issue = Issue(
            thread_id=thread.id,
            issue_number=issue_number,
            position=position,
            status="unread",
            created_at=now,
        )
        async_db.add(issue)
        issues[issue_number] = issue
    await async_db.flush()
    thread.next_unread_issue_id = issues[next_unread_number].id
    await async_db.commit()
    await async_db.refresh(thread)
    for issue in issues.values():
        await async_db.refresh(issue)
    return thread, issues


@pytest.mark.asyncio
async def test_direct_rate_without_session_persists_and_advances_frontier(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A Thread row rating works with no active reading session and no Roll."""
    thread, issues = await _create_issue_tracked_thread(async_db, default_user.id)

    response = await auth_client.post(
        "/api/v1/rate/",
        json={
            "rating": 4.0,
            "thread_id": thread.id,
            "direct": True,
            "issue_number": "1",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["last_rating"] == 4.0
    assert data["issues_remaining"] == 2
    assert data["next_unread_issue_number"] == "2"

    await async_db.refresh(thread)
    await async_db.refresh(issues["1"])
    assert thread.next_unread_issue_id == issues["2"].id
    assert thread.issues_remaining == 2
    assert thread.reading_progress == "in_progress"
    assert issues["1"].status == "read"
    assert issues["1"].read_at is not None

    event_result = await async_db.execute(
        select(Event).where(Event.type == "rate").where(Event.thread_id == thread.id)
    )
    event = event_result.scalar_one()
    # A direct rating now creates the reading session its undo record needs, so
    # the event belongs to that session even though no Roll was launched.
    assert event.session_id is not None
    assert event.issue_id == issues["1"].id
    assert event.issue_number == "1"
    assert event.die_after is None
    assert event.source_roll_event_id is None
    assert data["session_id"] == event.session_id
    assert data["undo_snapshot_id"] is not None

    # One session and a session-start checkpoint plus the rating's undo record.
    session_count = await async_db.scalar(select(func.count()).select_from(ReadingSession))
    snapshot_count = await async_db.scalar(select(func.count()).select_from(Snapshot))
    assert session_count == 1
    assert snapshot_count == 2
    assert issues["1"].last_rating == 4.0


@pytest.mark.asyncio
async def test_each_issue_row_keeps_its_own_saved_rating(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Rated rows return their own rating, not the thread's latest rating."""
    thread, issues = await _create_issue_tracked_thread(async_db, default_user.id)

    first = await auth_client.post(
        "/api/v1/rate/",
        json={
            "rating": 5.0,
            "thread_id": thread.id,
            "direct": True,
            "issue_number": "1",
        },
    )
    second = await auth_client.post(
        "/api/v1/rate/",
        json={
            "rating": 2.0,
            "thread_id": thread.id,
            "direct": True,
            "issue_number": "2",
        },
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["last_rating"] == 2.0

    listed = await auth_client.get(f"/api/v1/threads/{thread.id}/issues")
    assert listed.status_code == 200
    rating_by_number = {
        row["issue_number"]: row["last_rating"] for row in listed.json()["issues"]
    }
    assert rating_by_number == {"1": 5.0, "2": 2.0, "3": None}


@pytest.mark.asyncio
async def test_direct_rate_leaves_unrelated_pending_roll_and_die_untouched(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Rating from a Thread row never retires or changes an unrelated pending Roll."""
    rated_thread, _ = await _create_issue_tracked_thread(async_db, default_user.id)
    pending_thread = Thread(
        title="Pending Roll",
        format="Comic",
        issues_remaining=3,
        total_issues=3,
        queue_position=2,
        status="active",
        reading_progress="in_progress",
        user_id=default_user.id,
    )
    async_db.add(pending_thread)
    await async_db.flush()
    session = ReadingSession(
        start_die=6,
        manual_die=8,
        user_id=default_user.id,
        pending_thread_id=pending_thread.id,
        pending_thread_updated_at=datetime.now(UTC),
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    response = await auth_client.post(
        "/api/v1/rate/",
        json={
            "rating": 5.0,
            "thread_id": rated_thread.id,
            "direct": True,
            "issue_number": "1",
        },
    )

    assert response.status_code == 200
    await async_db.refresh(session)
    assert session.pending_thread_id == pending_thread.id
    assert session.pending_thread_updated_at is not None

    event_result = await async_db.execute(
        select(Event).where(Event.type == "rate").where(Event.thread_id == rated_thread.id)
    )
    event = event_result.scalar_one()
    assert event.session_id == session.id
    # A rating outside Roll must not move the die ladder.
    assert event.die_after is None
    assert event.source_roll_event_id is None


@pytest.mark.asyncio
async def test_direct_rate_records_undo_snapshot_and_undo_restores_state(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """With an active session, a direct rating is undoable like a Roll rating."""
    thread, issues = await _create_issue_tracked_thread(async_db, default_user.id)
    session = ReadingSession(start_die=6, user_id=default_user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    response = await auth_client.post(
        "/api/v1/rate/",
        json={
            "rating": 3.0,
            "thread_id": thread.id,
            "direct": True,
            "issue_number": "2",
        },
    )
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["next_unread_issue_number"] == "1"
    assert response_data["session_id"] == session.id
    assert response_data["undo_snapshot_id"] is not None

    await async_db.refresh(thread)
    await async_db.refresh(issues["2"])
    assert issues["2"].status == "read"
    assert issues["2"].last_rating == 3.0
    assert thread.next_unread_issue_id == issues["1"].id

    snapshots_response = await auth_client.get(f"/api/v1/undo/{session.id}/snapshots")
    assert snapshots_response.status_code == 200
    snapshots = snapshots_response.json()["snapshots"]
    assert len(snapshots) == 1
    assert snapshots[0]["description"] == "After rating"
    assert snapshots[0]["id"] == response_data["undo_snapshot_id"]

    undo_response = await auth_client.post(
        f"/api/v1/undo/{session.id}/undo/{snapshots[0]['id']}"
    )
    assert undo_response.status_code == 200

    await async_db.refresh(thread)
    await async_db.refresh(issues["2"])
    assert issues["2"].status == "unread"
    assert issues["2"].read_at is None
    assert issues["2"].last_rating is None
    assert thread.next_unread_issue_id == issues["1"].id
    assert thread.issues_remaining == 3
    assert thread.last_rating is None


@pytest.mark.asyncio
async def test_direct_rate_rejects_another_readers_thread(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Ownership is enforced for explicit direct Thread ratings."""
    from tests.conftest import get_or_create_user_async

    other_user = await get_or_create_user_async(async_db, username="other-reader")
    thread, _ = await _create_issue_tracked_thread(async_db, other_user.id)

    response = await auth_client.post(
        "/api/v1/rate/",
        json={
            "rating": 4.0,
            "thread_id": thread.id,
            "direct": True,
            "issue_number": "1",
        },
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_direct_rate_requires_thread_id(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A direct rating without its explicit thread is rejected, not silently rolled."""
    await _create_issue_tracked_thread(async_db, default_user.id)

    response = await auth_client.post(
        "/api/v1/rate/", json={"rating": 4.0, "direct": True, "issue_number": "1"}
    )

    assert response.status_code == 400
    assert "thread_id" in response.json()["detail"]


@pytest.mark.asyncio
async def test_direct_rate_unknown_issue_is_rejected(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A direct rating names one concrete issue and does not guess a different one."""
    thread, _ = await _create_issue_tracked_thread(async_db, default_user.id)

    response = await auth_client.post(
        "/api/v1/rate/",
        json={
            "rating": 4.0,
            "thread_id": thread.id,
            "direct": True,
            "issue_number": "99",
        },
    )

    assert response.status_code == 404
    await async_db.refresh(thread)
    assert thread.issues_remaining == 3


@pytest.mark.asyncio
async def test_thread_id_without_direct_keeps_roll_session_contract(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A Roll request that merely carries thread_id still requires a session."""
    thread, _ = await _create_issue_tracked_thread(async_db, default_user.id)

    response = await auth_client.post(
        "/api/v1/rate/",
        json={
            "rating": 4.0,
            "thread_id": thread.id,
            "issue_number": "1",
        },
    )

    assert response.status_code == 400
    assert "No active session" in response.json()["detail"]
