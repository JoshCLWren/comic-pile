"""Completion-path regression tests for version-two undo snapshots."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dependency, Event, Issue, Snapshot, Thread, User
from app.models import Session as SessionModel
from app.services.snapshot_contract import (
    BLOCKED_CHANGES_KEY,
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
async def test_delta_undo_restores_completed_session_state(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Prove a version-two undo reverses a real session completion.

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
        title="Finish Session Series",
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
    assert undo_response.json()["current_die"] == 6

    await async_db.refresh(session)
    assert session.ended_at is None


@pytest.mark.asyncio
async def test_delta_undo_restores_dependency_blocked_transition(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Prove completion unblocks a dependent thread and undo re-blocks it.

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
        is_blocked=False,
        user_id=default_user.id,
    )
    target_thread = Thread(
        title="Dependency Target",
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
    assert snapshot.thread_states[BLOCKED_CHANGES_KEY] == {
        str(target_thread.id): True,
    }

    await async_db.refresh(source_issue)
    await async_db.refresh(target_thread)
    assert source_issue.status == "read"
    assert target_thread.is_blocked is False

    undo_response = await auth_client.post(
        f"/api/undo/{session.id}/undo/{snapshot.id}",
    )
    assert undo_response.status_code == 200

    await async_db.refresh(source_issue)
    await async_db.refresh(target_thread)
    assert source_issue.status == "unread"
    assert target_thread.is_blocked is True
