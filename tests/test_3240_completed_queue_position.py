"""Regression coverage for #3240: completed threads must not hold queue slots.

A completed thread used to keep the position it held while active, so an
archived series still advertised a live slot (the reported "COMPLETED /
Position #25" pairing) and the active queue behind it skipped a number.
Completion now parks the thread at ``queue_position = 0`` and closes the gap,
and every path that brings the thread back has to hand a real slot out again.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Issue, ReadingSession, Thread
from tests.conftest import get_or_create_user_async


async def _positions(async_db: AsyncSession, *threads: Thread) -> list[int]:
    """Refresh threads and return their queue positions in argument order.

    Args:
        async_db: Test database session.
        threads: Threads to reload before reading their queue positions.

    Returns:
        Queue position of each thread, in the order supplied.
    """
    positions: list[int] = []
    for thread in threads:
        await async_db.refresh(thread)
        positions.append(thread.queue_position)
    return positions


@pytest.mark.asyncio
async def test_rating_final_issue_releases_queue_slot(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Rating the last issue vacates the slot and closes the queue gap."""
    user = await get_or_create_user_async(async_db)

    session = ReadingSession(start_die=6, user_id=user.id)
    threads = [
        Thread(
            title=f"Series {position}",
            format="Comic",
            issues_remaining=1 if position == 2 else 4,
            queue_position=position,
            status="active",
            user_id=user.id,
        )
        for position in (1, 2, 3)
    ]
    async_db.add(session)
    async_db.add_all(threads)
    await async_db.commit()
    await async_db.refresh(session)

    async_db.add(
        Event(
            type="roll",
            session_id=session.id,
            thread_id=threads[1].id,
            selected_thread_id=threads[1].id,
            die=6,
            result=1,
        )
    )
    await async_db.commit()

    response = await auth_client.post("/api/v1/rate/", json={"rating": 5.0, "issues_read": 1})
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "completed"
    assert body["queue_position"] == 0

    # The completed thread holds no slot and the queue behind it closes up.
    assert await _positions(async_db, *threads) == [1, 0, 2]


@pytest.mark.asyncio
async def test_marking_last_issue_read_releases_queue_slot(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Reading an issue tracked thread's final issue vacates its slot."""
    user = await get_or_create_user_async(async_db)

    tracked = Thread(
        title="Tracked",
        format="Comic",
        issues_remaining=1,
        total_issues=1,
        reading_progress="in_progress",
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    follower = Thread(
        title="Follower",
        format="Comic",
        issues_remaining=4,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    async_db.add_all([tracked, follower])
    await async_db.commit()
    await async_db.refresh(tracked)

    issue = Issue(thread_id=tracked.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.commit()
    await async_db.refresh(issue)

    tracked.next_unread_issue_id = issue.id
    await async_db.commit()

    response = await auth_client.post(f"/api/v1/issues/{issue.id}:markRead")
    assert response.status_code == 204

    assert await _positions(async_db, tracked, follower) == [0, 1]


@pytest.mark.asyncio
async def test_bulk_marking_issues_read_releases_queue_slot(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Bulk-reading the last unread issues also vacates the queue slot."""
    user = await get_or_create_user_async(async_db)

    tracked = Thread(
        title="Bulk Tracked",
        format="Comic",
        issues_remaining=2,
        total_issues=2,
        reading_progress="in_progress",
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    leader = Thread(
        title="Leader",
        format="Comic",
        issues_remaining=9,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add_all([leader, tracked])
    await async_db.commit()
    await async_db.refresh(tracked)

    issues = [
        Issue(thread_id=tracked.id, issue_number=str(number), position=number, status="unread")
        for number in (1, 2)
    ]
    async_db.add_all(issues)
    await async_db.commit()

    tracked.next_unread_issue_id = issues[0].id
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/issues:bulkMarkRead",
        json={"issue_ids": [issue.id for issue in issues]},
    )
    assert response.status_code == 204

    assert await _positions(async_db, leader, tracked) == [1, 0]


@pytest.mark.asyncio
async def test_marking_issue_unread_returns_thread_to_queue_front(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A completed thread parked at position 0 is re-seated when it revives."""
    user = await get_or_create_user_async(async_db)

    completed = Thread(
        title="Reviving",
        format="Comic",
        issues_remaining=0,
        total_issues=2,
        reading_progress="completed",
        queue_position=0,
        status="completed",
        user_id=user.id,
    )
    queued = Thread(
        title="Queued",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add_all([completed, queued])
    await async_db.commit()
    await async_db.refresh(completed)

    issues = [
        Issue(
            thread_id=completed.id,
            issue_number=str(number),
            position=number,
            status="read",
            read_at=datetime.now(UTC),
        )
        for number in (1, 2)
    ]
    async_db.add_all(issues)
    await async_db.commit()
    await async_db.refresh(issues[0])

    response = await auth_client.post(f"/api/v1/issues/{issues[0].id}:markUnread")
    assert response.status_code == 204

    # The revived thread takes the front slot and displaces the queued thread.
    assert await _positions(async_db, completed, queued) == [1, 2]
    await async_db.refresh(completed)
    assert completed.status == "active"
    assert completed.issues_remaining == 1


@pytest.mark.asyncio
async def test_editing_issues_remaining_releases_and_reclaims_queue_slot(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A counter-based thread vacates its slot at 0 and reclaims it on edit."""
    user = await get_or_create_user_async(async_db)

    legacy = Thread(
        title="Counter Based",
        format="Comic",
        issues_remaining=4,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    leader = Thread(
        title="Leader",
        format="Comic",
        issues_remaining=9,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add_all([leader, legacy])
    await async_db.commit()

    complete_response = await auth_client.put(
        f"/api/v1/threads/{legacy.id}",
        json={"issues_remaining": 0},
    )
    assert complete_response.status_code == 200
    assert complete_response.json()["queue_position"] == 0

    assert await _positions(async_db, leader, legacy) == [1, 0]

    revive_response = await auth_client.put(
        f"/api/v1/threads/{legacy.id}",
        json={"issues_remaining": 4},
    )
    assert revive_response.status_code == 200
    assert revive_response.json()["queue_position"] == 1

    assert await _positions(async_db, leader, legacy) == [2, 1]


@pytest.mark.asyncio
async def test_migrating_fully_read_thread_releases_queue_slot(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Migrating a fully-read thread completes it, so it vacates its slot."""
    user = await get_or_create_user_async(async_db)

    legacy = Thread(
        title="Fully Read",
        format="Comic",
        issues_remaining=3,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    follower = Thread(
        title="Follower",
        format="Comic",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    async_db.add_all([legacy, follower])
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{legacy.id}:migrateToIssues",
        json={"last_issue_read": 3, "total_issues": 3},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["queue_position"] == 0

    assert await _positions(async_db, legacy, follower) == [0, 1]
