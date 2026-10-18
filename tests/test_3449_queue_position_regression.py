"""Regression tests for #3449: dense queue positions after queue mutations.

The Queue page renders each active series at its dense 1..N index, while the
roll card ("#N in queue") and the thread page ("Position #N") render the stored
``queue_position``. Those surfaces only agree when the stored positions stay a
contiguous ``1..N`` sequence, so completing or deleting a series must close the
gap it leaves and no displayed position may exceed the number of active
series.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread, User
from app.schemas.thread import ThreadUpdate
from app.services import issue as issue_service
from app.services import thread_service


async def _active_positions(async_db: AsyncSession, user_id: int) -> list[int]:
    """Return the stored active-queue positions for one reader, lowest first."""
    result = await async_db.execute(
        select(Thread.queue_position)
        .where(Thread.user_id == user_id, Thread.status == "active")
        .order_by(Thread.queue_position)
    )
    return list(result.scalars().all())


async def _add_thread(
    async_db: AsyncSession,
    user: User,
    *,
    title: str,
    position: int,
    total_issues: int | None = None,
) -> Thread:
    """Insert one active thread at ``position`` and return it."""
    thread = Thread(
        title=title,
        format="comic",
        user_id=user.id,
        queue_position=position,
        status="active",
        issues_remaining=1 if total_issues is None else total_issues,
        total_issues=total_issues,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    return thread


def _assert_dense(positions: list[int]) -> None:
    """Assert ``positions`` is exactly ``1..N`` with no reusable gap."""
    assert positions == list(range(1, len(positions) + 1)), positions
    assert max(positions, default=0) <= len(positions)


@pytest.mark.asyncio
async def test_delete_thread_keeps_positions_dense(
    async_db: AsyncSession, default_user: User
) -> None:
    """Deleting a middle series closes the gap in the active queue."""
    await _add_thread(async_db, default_user, title="A", position=1)
    middle = await _add_thread(async_db, default_user, title="B", position=2)
    await _add_thread(async_db, default_user, title="C", position=3)
    await async_db.commit()

    await thread_service.delete_thread(async_db, default_user.id, middle.id)

    _assert_dense(await _active_positions(async_db, default_user.id))


@pytest.mark.asyncio
async def test_complete_thread_via_update_keeps_positions_dense(
    async_db: AsyncSession, default_user: User
) -> None:
    """Completing a counter-based series by editing issues closes the gap."""
    await _add_thread(async_db, default_user, title="A", position=1)
    middle = await _add_thread(async_db, default_user, title="B", position=2)
    await _add_thread(async_db, default_user, title="C", position=3)
    await async_db.commit()

    await thread_service.update_thread(
        async_db, default_user.id, middle.id, ThreadUpdate(issues_remaining=0)
    )

    await async_db.refresh(middle)
    assert middle.status == "completed"
    _assert_dense(await _active_positions(async_db, default_user.id))


@pytest.mark.asyncio
async def test_complete_thread_via_mark_read_keeps_positions_dense(
    async_db: AsyncSession, default_user: User
) -> None:
    """Reading the last issue completes a series without leaving a queue gap."""
    await _add_thread(async_db, default_user, title="A", position=1)
    tracked = await _add_thread(
        async_db, default_user, title="B", position=2, total_issues=1
    )
    await _add_thread(async_db, default_user, title="C", position=3)

    last_issue = Issue(
        thread_id=tracked.id,
        issue_number="1",
        position=1,
        status="unread",
        read_at=None,
    )
    async_db.add(last_issue)
    await async_db.commit()

    await issue_service.mark_issue_read(async_db, last_issue.id, default_user.id)
    await async_db.commit()

    await async_db.refresh(tracked)
    assert tracked.status == "completed"
    _assert_dense(await _active_positions(async_db, default_user.id))


@pytest.mark.asyncio
async def test_reactivate_thread_via_mark_unread_keeps_positions_dense(
    async_db: AsyncSession, default_user: User
) -> None:
    """Reactivating a completed series re-enters the dense active queue."""
    await _add_thread(async_db, default_user, title="A", position=1)
    await _add_thread(async_db, default_user, title="C", position=2)

    completed = Thread(
        title="B",
        format="comic",
        user_id=default_user.id,
        queue_position=0,
        status="completed",
        issues_remaining=0,
        total_issues=1,
        reading_progress="completed",
        created_at=datetime.now(UTC),
    )
    async_db.add(completed)
    await async_db.flush()

    read_issue = Issue(
        thread_id=completed.id,
        issue_number="1",
        position=1,
        status="read",
        read_at=datetime.now(UTC),
    )
    async_db.add(read_issue)
    await async_db.commit()

    await issue_service.mark_issue_unread(async_db, read_issue.id, default_user.id)
    await async_db.commit()

    await async_db.refresh(completed)
    assert completed.status == "active"
    _assert_dense(await _active_positions(async_db, default_user.id))
