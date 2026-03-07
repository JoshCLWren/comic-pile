"""Regression tests for issue position preservation in snapshots and undo."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.rate import snapshot_thread_states
from app.api.undo import undo_to_snapshot
from app.models import Event, Issue, Snapshot, Thread
from app.models import Session as SessionModel
from app.models.user import User


async def _create_session_event(
    async_db: AsyncSession,
    user: User,
    thread: Thread,
    event_type: str = "rate",
) -> tuple[SessionModel, Event]:
    """Create a session/event pair for snapshot and undo tests."""
    session = SessionModel(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.flush()

    event = Event(
        type=event_type,
        session_id=session.id,
        thread_id=thread.id,
        timestamp=datetime.now(UTC),
    )
    async_db.add(event)
    await async_db.flush()
    return session, event


@pytest.mark.asyncio
async def test_snapshot_includes_issue_positions(
    async_db: AsyncSession, default_user: User
) -> None:
    """Snapshot serialization persists explicit issue positions."""
    thread = Thread(
        title="Test Thread",
        format="comic",
        user_id=default_user.id,
        queue_position=1,
        total_issues=3,
        status="active",
        reading_progress="in_progress",
    )
    async_db.add(thread)
    await async_db.flush()

    async_db.add_all(
        [
            Issue(
                id=100,
                thread_id=thread.id,
                issue_number="1",
                position=5,
                status="read",
                read_at=datetime.now(UTC),
            ),
            Issue(
                id=101,
                thread_id=thread.id,
                issue_number="2",
                position=10,
                status="unread",
            ),
            Issue(
                id=102,
                thread_id=thread.id,
                issue_number="3",
                position=15,
                status="unread",
            ),
        ]
    )
    await async_db.flush()

    session, event = await _create_session_event(async_db, default_user, thread)
    await snapshot_thread_states(async_db, session.id, event.id, default_user.id, commit=False)
    await async_db.flush()

    snapshot_result = await async_db.execute(
        select(Snapshot)
        .where(Snapshot.session_id == session.id)
        .where(Snapshot.event_id == event.id)
        .order_by(Snapshot.id.desc())
    )
    snapshot = snapshot_result.scalar_one()

    issue_states = snapshot.thread_states[str(thread.id)]["issue_states"]
    assert [issue_state["position"] for issue_state in issue_states] == [5, 10, 15]


@pytest.mark.asyncio
async def test_undo_restore_preserves_positions_with_fallback(
    async_db: AsyncSession, default_user: User
) -> None:
    """Undo restore assigns sequential positions for legacy snapshots."""
    thread = Thread(
        id=999,
        title="Legacy Thread",
        format="comic",
        user_id=default_user.id,
        queue_position=1,
        status="active",
    )
    async_db.add(thread)
    await async_db.flush()

    session, event = await _create_session_event(async_db, default_user, thread)
    snapshot = Snapshot(
        session_id=session.id,
        event_id=event.id,
        description="After rating",
        thread_states={
            str(thread.id): {
                "title": "Legacy Thread",
                "format": "comic",
                "issues_remaining": 2,
                "queue_position": 1,
                "status": "active",
                "issue_states": [
                    {
                        "id": 200,
                        "number": "1",
                        "status": "read",
                        "read_at": datetime.now(UTC).isoformat(),
                    },
                    {
                        "id": 201,
                        "number": "2",
                        "status": "unread",
                        "read_at": None,
                    },
                ],
            }
        },
        session_state={"start_die": 6, "manual_die": None},
    )
    async_db.add(snapshot)
    await async_db.commit()

    await undo_to_snapshot(session.id, snapshot.id, default_user, async_db)

    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position, Issue.id)
    )
    issues = result.scalars().all()

    assert [issue.position for issue in issues] == [1, 2]
    assert [issue.issue_number for issue in issues] == ["1", "2"]


@pytest.mark.asyncio
async def test_undo_restore_replaces_existing_issues_before_fallback_numbering(
    async_db: AsyncSession, default_user: User
) -> None:
    """Undo restore replaces existing issues and renumbers legacy payloads from one."""
    thread = Thread(
        id=888,
        title="Test Thread",
        format="comic",
        user_id=default_user.id,
        queue_position=1,
        status="active",
    )
    async_db.add(thread)
    await async_db.flush()

    async_db.add(
        Issue(
            id=300,
            thread_id=thread.id,
            issue_number="0",
            position=10,
            status="read",
            read_at=datetime.now(UTC),
        )
    )
    await async_db.flush()

    session, event = await _create_session_event(async_db, default_user, thread)
    snapshot = Snapshot(
        session_id=session.id,
        event_id=event.id,
        description="After rating",
        thread_states={
            str(thread.id): {
                "title": "Test Thread",
                "format": "comic",
                "issues_remaining": 2,
                "queue_position": 1,
                "status": "active",
                "issue_states": [
                    {
                        "id": 301,
                        "number": "1",
                        "status": "unread",
                        "read_at": None,
                    },
                    {
                        "id": 302,
                        "number": "2",
                        "status": "unread",
                        "read_at": None,
                    },
                ],
            }
        },
        session_state={"start_die": 6, "manual_die": None},
    )
    async_db.add(snapshot)
    await async_db.commit()

    await undo_to_snapshot(session.id, snapshot.id, default_user, async_db)

    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position, Issue.id)
    )
    issues = result.scalars().all()

    assert [issue.id for issue in issues] == [301, 302]
    assert [issue.position for issue in issues] == [1, 2]
