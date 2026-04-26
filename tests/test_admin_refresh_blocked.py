"""Regression tests for fix_stale_blocked_flags script.

Verifies that refresh_user_blocked_status (the core of the script) correctly
recalculates stale is_blocked flags after the next-unread-only blocking logic:
- Threads stamped is_blocked=True by old range-based logic must be cleared when
  the dependency's target issue is not the next unread issue.
- Threads that are genuinely blocked must remain blocked after recalculation.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dependency, Issue, Thread, User
from comic_pile.dependencies import refresh_user_blocked_status
from comic_pile.queue import get_roll_pool


@pytest.mark.asyncio
async def test_stale_blocked_flag_cleared_after_refresh(async_db: AsyncSession) -> None:
    """Stale is_blocked=True flags must be cleared when next_unread is past the dep target.

    Regression: range-based logic blocked whenever a dependency target was at or
    after next_unread. Next-unread-only logic must clear stale flags unless the
    dependency target is exactly the next unread issue.
    """
    user = User(username="stale_flag_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    source = Thread(
        title="Source",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    target = Thread(
        title="Target",
        format="Comic",
        issues_remaining=3,
        queue_position=2,
        status="active",
        user_id=user.id,
        is_blocked=True,
    )
    async_db.add_all([source, target])
    await async_db.flush()

    source_issue = Issue(thread_id=source.id, issue_number="1", position=1, status="unread")
    target_issue_1 = Issue(thread_id=target.id, issue_number="1", position=1, status="read")
    target_issue_2 = Issue(thread_id=target.id, issue_number="2", position=2, status="read")
    target_issue_3 = Issue(thread_id=target.id, issue_number="3", position=3, status="unread")
    async_db.add_all([source_issue, target_issue_1, target_issue_2, target_issue_3])
    await async_db.flush()

    source.next_unread_issue_id = source_issue.id
    target.next_unread_issue_id = target_issue_3.id
    async_db.add(Dependency(source_issue_id=source_issue.id, target_issue_id=target_issue_2.id))
    await async_db.commit()

    await async_db.refresh(target)
    assert target.is_blocked is True

    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()
    await async_db.refresh(target)

    assert target.is_blocked is False
    pool = await get_roll_pool(user.id, async_db)
    assert target.id in [t.id for t in pool]


@pytest.mark.asyncio
async def test_legitimately_blocked_thread_stays_blocked_after_refresh(
    async_db: AsyncSession,
) -> None:
    """Threads blocked by their next unread issue must remain blocked after refresh."""
    user = User(username="legit_blocked_user", created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.flush()

    source = Thread(
        title="Must Read First",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    target = Thread(
        title="Blocked Until Source Done",
        format="Comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
        is_blocked=False,
    )
    async_db.add_all([source, target])
    await async_db.flush()

    source_issue = Issue(thread_id=source.id, issue_number="1", position=1, status="unread")
    target_issue = Issue(thread_id=target.id, issue_number="1", position=1, status="unread")
    async_db.add_all([source_issue, target_issue])
    await async_db.flush()

    source.next_unread_issue_id = source_issue.id
    target.next_unread_issue_id = target_issue.id  # next unread is #1
    # dependency is on next unread — should block
    async_db.add(Dependency(source_issue_id=source_issue.id, target_issue_id=target_issue.id))
    await async_db.commit()

    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()
    await async_db.refresh(target)

    assert target.is_blocked is True
    pool = await get_roll_pool(user.id, async_db)
    assert target.id not in [t.id for t in pool]
