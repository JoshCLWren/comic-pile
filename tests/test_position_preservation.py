"""Test position preservation in snapshots/undo."""

from datetime import UTC, datetime
from typing import TypedDict

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread


class IssueState(TypedDict, total=False):
    """Serialized issue state used in snapshot/restore tests."""

    id: int
    number: str
    status: str
    read_at: str | None
    position: int


class ThreadState(TypedDict):
    """Serialized thread state used in snapshot/restore tests."""

    title: str
    format: str
    issues_remaining: int | None
    queue_position: int
    status: str
    issue_states: list[IssueState]


@pytest.mark.asyncio
async def test_snapshot_includes_issue_positions(
    async_db: AsyncSession, default_user
) -> None:
    """Test that snapshots preserve issue positions."""
    # Create thread with issues at specific positions
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

    # Create issues with specific positions
    issue1 = Issue(
        id=100,
        thread_id=thread.id,
        issue_number="1",
        position=5,
        status="read",
        read_at=datetime.now(UTC),
    )
    issue2 = Issue(
        id=101,
        thread_id=thread.id,
        issue_number="2",
        position=10,
        status="unread",
    )
    issue3 = Issue(
        id=102,
        thread_id=thread.id,
        issue_number="3",
        position=15,
        status="unread",
    )
    async_db.add_all([issue1, issue2, issue3])
    await async_db.flush()

    # Create snapshot (simulating rate endpoint behavior)
    thread_states: dict[int, ThreadState] = {}
    base_state: ThreadState = {
        "title": thread.title,
        "format": thread.format,
        "issues_remaining": thread.issues_remaining,
        "queue_position": thread.queue_position,
        "status": thread.status,
        "issue_states": [],
    }

    issues_result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    issues = issues_result.scalars().all()

    base_state["issue_states"] = [
        {
            "id": issue.id,
            "number": issue.issue_number,
            "status": issue.status,
            "read_at": issue.read_at.isoformat() if issue.read_at else None,
            "position": issue.position,
        }
        for issue in issues
    ]
    thread_states[thread.id] = base_state

    # Verify positions are in snapshot
    assert thread_states[thread.id]["issue_states"][0]["position"] == 5
    assert thread_states[thread.id]["issue_states"][1]["position"] == 10
    assert thread_states[thread.id]["issue_states"][2]["position"] == 15


@pytest.mark.asyncio
async def test_restore_preserves_positions_with_fallback(
    async_db: AsyncSession, default_user
) -> None:
    """Test that session restore preserves positions with safe fallback."""
    # Create snapshot with missing position (legacy data)
    thread_states: dict[int, ThreadState] = {
        999: {
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
    }

    # Create thread
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

    # Simulate restoration logic from session.py
    from sqlalchemy import delete

    state = thread_states[999]
    thread_id_int = 999

    await async_db.execute(delete(Issue).where(Issue.thread_id == thread_id_int))

    # Get existing positions (none exist yet)
    existing_positions_result = await async_db.execute(
        select(Issue.position).where(Issue.thread_id == thread_id_int)
    )
    existing_positions = existing_positions_result.scalars().all()
    max_position = max(existing_positions) if existing_positions else 0

    # Restore issues with fallback logic
    for issue_state in state["issue_states"]:
        position = issue_state.get("position", max_position + 1)
        if position > max_position:
            max_position = position
        issue = Issue(
            id=issue_state["id"],
            thread_id=thread_id_int,
            issue_number=issue_state["number"],
            status=issue_state["status"],
            read_at=datetime.fromisoformat(issue_state["read_at"])
            if issue_state["read_at"]
            else None,
            created_at=datetime.now(UTC),
            position=position,
        )
        async_db.add(issue)

    await async_db.flush()

    # Verify positions were assigned correctly
    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread_id_int).order_by(Issue.position)
    )
    issues = result.scalars().all()

    assert issues[0].position == 1
    assert issues[1].position == 2


@pytest.mark.asyncio
async def test_restore_fallback_assigns_sequential_positions_after_replace(
    async_db: AsyncSession, default_user
) -> None:
    """Test that restore fallback renumbers legacy issues sequentially after replace."""
    # Create thread with pre-existing issues that will be replaced during restore.
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

    existing_issue = Issue(
        id=300,
        thread_id=thread.id,
        issue_number="0",
        position=10,
        status="read",
        read_at=datetime.now(UTC),
    )
    async_db.add(existing_issue)
    await async_db.flush()

    # Restore snapshot with issues (without position field - legacy)
    from sqlalchemy import delete

    snapshot_state: ThreadState = {
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

    await async_db.execute(delete(Issue).where(Issue.thread_id == thread.id))

    # Get existing positions
    existing_positions_result = await async_db.execute(
        select(Issue.position).where(Issue.thread_id == thread.id)
    )
    existing_positions = existing_positions_result.scalars().all()
    max_position = max(existing_positions) if existing_positions else 0

    # Restore with fallback logic
    for issue_state in snapshot_state["issue_states"]:
        position = issue_state.get("position", max_position + 1)
        if position > max_position:
            max_position = position
        issue = Issue(
            id=issue_state["id"],
            thread_id=thread.id,
            issue_number=issue_state["number"],
            status=issue_state["status"],
            read_at=datetime.fromisoformat(issue_state["read_at"])
            if issue_state["read_at"]
            else None,
            created_at=datetime.now(UTC),
            position=position,
        )
        async_db.add(issue)

    await async_db.flush()

    # Verify no collision and sequential positions
    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    issues = result.scalars().all()

    assert len(issues) == 2
    assert issues[0].position == 1
    assert issues[1].position == 2
