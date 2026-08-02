"""Regression tests for version-two rating undo snapshots."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dependency, Event, Issue, Review, Snapshot, Thread, User
from app.models import Session as SessionModel
from app.services.snapshot_contract import (
    BLOCKED_CHANGES_KEY,
    QUEUE_CHANGES_KEY,
    SNAPSHOT_VERSION,
    SNAPSHOT_VERSION_KEY,
)


async def _latest_snapshot(db: AsyncSession, session_id: int) -> Snapshot:
    """Return the newest snapshot for a session."""
    result = await db.execute(
        select(Snapshot)
        .where(Snapshot.session_id == session_id)
        .order_by(Snapshot.id.desc())
    )
    snapshot = result.scalars().first()
    assert snapshot is not None
    return snapshot


@pytest.mark.asyncio
async def test_delta_undo_preserves_issue_associations_and_die(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Preserve issue-linked data while restoring progress and die state.

    Args:
        auth_client: Authenticated HTTP test client.
        async_db: Test database session.
        default_user: Authenticated test user.

    Returns:
        None.
    """
    session = SessionModel(
        start_die=6,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    thread = Thread(
        title="Mapped Series",
        format="comic",
        issues_remaining=2,
        total_issues=2,
        reading_progress="in_progress",
        queue_position=1,
        status="active",
        user_id=default_user.id,
    )
    async_db.add_all([session, thread])
    await async_db.commit()
    await async_db.refresh(session)
    await async_db.refresh(thread)

    issue_one = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    issue_two = Issue(
        thread_id=thread.id,
        issue_number="2",
        position=2,
        status="unread",
    )
    async_db.add_all([issue_one, issue_two])
    await async_db.commit()
    await async_db.refresh(issue_one)
    await async_db.refresh(issue_two)

    thread.next_unread_issue_id = issue_one.id
    dependency = Dependency(
        source_issue_id=issue_one.id,
        target_issue_id=issue_two.id,
    )
    review = Review(
        user_id=default_user.id,
        thread_id=thread.id,
        issue_id=issue_one.id,
        rating=4.5,
        review_text="Keep this attached.",
    )
    roll_event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        issue_id=issue_one.id,
        die=6,
        result=1,
    )
    async_db.add_all([dependency, review, roll_event])
    await async_db.commit()
    await async_db.refresh(dependency)
    await async_db.refresh(review)
    await async_db.refresh(roll_event)

    rate_response = await auth_client.post(
        "/api/rate/",
        json={"rating": 5.0, "issues_read": 1},
    )
    assert rate_response.status_code == 200

    snapshot = await _latest_snapshot(async_db, session.id)
    assert snapshot.thread_states[SNAPSHOT_VERSION_KEY] == SNAPSHOT_VERSION

    await async_db.refresh(issue_one)
    assert issue_one.status == "read"

    undo_response = await auth_client.post(
        f"/api/undo/{session.id}/undo/{snapshot.id}",
    )
    assert undo_response.status_code == 200
    assert undo_response.json()["current_die"] == 6

    restored_issue = await async_db.get(Issue, issue_one.id)
    assert restored_issue is not None
    assert restored_issue.status == "unread"
    assert restored_issue.read_at is None

    restored_dependency = await async_db.get(Dependency, dependency.id)
    assert restored_dependency is not None
    assert restored_dependency.source_issue_id == issue_one.id
    assert restored_dependency.target_issue_id == issue_two.id

    await async_db.refresh(review)
    await async_db.refresh(roll_event)
    assert review.issue_id == issue_one.id
    assert roll_event.issue_id == issue_one.id

    event_types_result = await async_db.execute(
        select(Event.type).where(Event.session_id == session.id).order_by(Event.id)
    )
    assert event_types_result.scalars().all() == ["roll", "rate", "undo"]


@pytest.mark.asyncio
async def test_delta_undo_reverses_implicit_issue_migration(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Return an implicitly migrated thread to counter-only tracking.

    Args:
        auth_client: Authenticated HTTP test client.
        async_db: Test database session.
        default_user: Authenticated test user.

    Returns:
        None.
    """
    session = SessionModel(
        start_die=6,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    thread = Thread(
        title="Legacy Counter Series",
        format="comic",
        issues_remaining=3,
        queue_position=1,
        status="active",
        user_id=default_user.id,
    )
    async_db.add_all([session, thread])
    await async_db.commit()
    await async_db.refresh(session)
    await async_db.refresh(thread)

    async_db.add(
        Event(
            type="roll",
            session_id=session.id,
            selected_thread_id=thread.id,
            die=6,
            result=1,
        )
    )
    await async_db.commit()

    rate_response = await auth_client.post(
        "/api/rate/",
        json={"rating": 5.0, "issues_read": 1, "issue_number": "1"},
    )
    assert rate_response.status_code == 200

    snapshot = await _latest_snapshot(async_db, session.id)
    assert snapshot.thread_states[SNAPSHOT_VERSION_KEY] == SNAPSHOT_VERSION

    await async_db.refresh(thread)
    assert thread.total_issues == 3
    issue_count = await async_db.scalar(
        select(func.count()).select_from(Issue).where(Issue.thread_id == thread.id)
    )
    assert issue_count == 3

    undo_response = await auth_client.post(
        f"/api/undo/{session.id}/undo/{snapshot.id}",
    )
    assert undo_response.status_code == 200
    assert undo_response.json()["current_die"] == 6

    await async_db.refresh(thread)
    assert thread.total_issues is None
    assert thread.next_unread_issue_id is None
    assert thread.reading_progress is None
    assert thread.issues_remaining == 3
    assert thread.last_rating is None
    assert thread.last_activity_at is None

    issue_count = await async_db.scalar(
        select(func.count()).select_from(Issue).where(Issue.thread_id == thread.id)
    )
    assert issue_count == 0

    rate_event_result = await async_db.execute(
        select(Event)
        .where(Event.session_id == session.id)
        .where(Event.type == "rate")
    )
    rate_event = rate_event_result.scalars().one()
    assert rate_event.issue_id is None
    assert rate_event.issue_number == "1"


@pytest.mark.asyncio
async def test_delta_snapshot_uses_queue_helper_change_set(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Store exactly the queue rows changed by a move-to-front rating.

    Args:
        auth_client: Authenticated HTTP test client.
        async_db: Test database session.
        default_user: Authenticated test user.

    Returns:
        None.
    """
    session = SessionModel(
        start_die=6,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    threads = [
        Thread(
            title=f"Queue Thread {position}",
            format="comic",
            issues_remaining=5,
            queue_position=position,
            status="active",
            user_id=default_user.id,
        )
        for position in range(1, 4)
    ]
    async_db.add_all([session, *threads])
    await async_db.commit()
    await async_db.refresh(session)
    for thread in threads:
        await async_db.refresh(thread)

    target = threads[2]
    async_db.add(
        Event(
            type="roll",
            session_id=session.id,
            selected_thread_id=target.id,
            die=6,
            result=3,
        )
    )
    await async_db.commit()

    rate_response = await auth_client.post(
        "/api/rate/",
        json={"rating": 5.0, "issues_read": 1},
    )
    assert rate_response.status_code == 200

    snapshot = await _latest_snapshot(async_db, session.id)
    assert snapshot.thread_states[SNAPSHOT_VERSION_KEY] == SNAPSHOT_VERSION
    queue_changes = snapshot.thread_states[QUEUE_CHANGES_KEY]
    assert queue_changes == {
        str(threads[0].id): 1,
        str(threads[1].id): 2,
        str(threads[2].id): 3,
    }

    for thread in threads:
        await async_db.refresh(thread)
    assert [thread.queue_position for thread in threads] == [2, 3, 1]

    undo_response = await auth_client.post(
        f"/api/undo/{session.id}/undo/{snapshot.id}",
    )
    assert undo_response.status_code == 200

    for thread in threads:
        await async_db.refresh(thread)
    assert [thread.queue_position for thread in threads] == [1, 2, 3]


@pytest.mark.asyncio
async def test_delta_undo_restores_finished_session_state(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Prove a v2 undo reverses the session completion mutation.

    Args:
        auth_client: Authenticated HTTP test client.
        async_db: Test database session.
        default_user: Authenticated test user.

    Returns:
        None.
    """
    session = SessionModel(
        start_die=6,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    thread = Thread(
        title="Session Finisher",
        format="comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=default_user.id,
    )
    async_db.add_all([session, thread])
    await async_db.commit()
    await async_db.refresh(session)
    await async_db.refresh(thread)

    async_db.add(
        Event(
            type="roll",
            session_id=session.id,
            selected_thread_id=thread.id,
            die=6,
            result=1,
        )
    )
    await async_db.commit()

    rate_response = await auth_client.post(
        "/api/rate/",
        json={"rating": 5.0, "issues_read": 1, "finish_session": True},
    )
    assert rate_response.status_code == 200

    snapshot = await _latest_snapshot(async_db, session.id)
    assert snapshot.thread_states[SNAPSHOT_VERSION_KEY] == SNAPSHOT_VERSION
    await async_db.refresh(session)
    assert session.ended_at is not None

    undo_response = await auth_client.post(
        f"/api/undo/{session.id}/undo/{snapshot.id}",
    )
    assert undo_response.status_code == 200
    await async_db.refresh(session)
    assert session.ended_at is None


@pytest.mark.asyncio
async def test_delta_undo_restores_deterministic_blocked_transition(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Restore a dependency-blocked flag changed by completing its source.

    Args:
        auth_client: Authenticated HTTP test client.
        async_db: Test database session.
        default_user: Authenticated test user.

    Returns:
        None.
    """
    session = SessionModel(
        start_die=6,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    source_thread = Thread(
        title="Dependency Source",
        format="comic",
        issues_remaining=1,
        total_issues=1,
        reading_progress="in_progress",
        queue_position=1,
        status="active",
        user_id=default_user.id,
    )
    target_thread = Thread(
        title="Blocked Target",
        format="comic",
        issues_remaining=1,
        total_issues=1,
        reading_progress="in_progress",
        queue_position=2,
        status="active",
        is_blocked=True,
        user_id=default_user.id,
    )
    async_db.add_all([session, source_thread, target_thread])
    await async_db.commit()
    await async_db.refresh(session)
    await async_db.refresh(source_thread)
    await async_db.refresh(target_thread)

    source_issue = Issue(
        thread_id=source_thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    target_issue = Issue(
        thread_id=target_thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    async_db.add_all([source_issue, target_issue])
    await async_db.commit()
    await async_db.refresh(source_issue)
    await async_db.refresh(target_issue)

    source_thread.next_unread_issue_id = source_issue.id
    target_thread.next_unread_issue_id = target_issue.id
    async_db.add(
        Dependency(
            source_issue_id=source_issue.id,
            target_issue_id=target_issue.id,
        )
    )
    async_db.add(
        Event(
            type="roll",
            session_id=session.id,
            selected_thread_id=source_thread.id,
            die=6,
            result=1,
        )
    )
    await async_db.commit()

    rate_response = await auth_client.post(
        "/api/rate/",
        json={"rating": 5.0, "issues_read": 1},
    )
    assert rate_response.status_code == 200

    snapshot = await _latest_snapshot(async_db, session.id)
    assert snapshot.thread_states[SNAPSHOT_VERSION_KEY] == SNAPSHOT_VERSION
    blocked_changes = snapshot.thread_states[BLOCKED_CHANGES_KEY]
    assert blocked_changes[str(target_thread.id)] is True

    await async_db.refresh(target_thread)
    assert target_thread.is_blocked is False

    undo_response = await auth_client.post(
        f"/api/undo/{session.id}/undo/{snapshot.id}",
    )
    assert undo_response.status_code == 200
    await async_db.refresh(target_thread)
    assert target_thread.is_blocked is True


@pytest.mark.asyncio
async def test_delta_snapshot_requires_rated_thread_id(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Reject a malformed delta payload before it becomes unrestorable.

    Args:
        async_db: Test database session.
        default_user: Authenticated test user.

    Returns:
        None.
    """
    from app.api.rate import snapshot_thread_states

    session = SessionModel(start_die=6, user_id=default_user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    event = Event(type="rate", session_id=session.id, rating=4.0)
    async_db.add(event)
    await async_db.commit()
    await async_db.refresh(event)

    with pytest.raises(ValueError, match="rated_thread_id is required"):
        await snapshot_thread_states(
            async_db,
            session.id,
            event.id,
            default_user.id,
            rated_thread_pre_state={},
        )
