"""Regression tests for fix_stale_blocked_flags script.

Verifies that refresh_user_blocked_status (the core of the script) correctly
recalculates stale is_blocked flags after the PR #299 logic change:
- Threads stamped is_blocked=True by the old broad logic must be cleared when
  the dependency only touches a future issue (not next_unread_issue_id).
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
    """Stale is_blocked=True flags must be cleared when the dep is on a future issue.

    Regression: old logic blocked any thread with a dependency on any of its
    issues. New logic only blocks when the dependency is on next_unread_issue_id.
    Threads already stamped True in the DB were not re-evaluated after deploy.
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
    # Stamped blocked by the old logic — dep is on a future issue, not next unread
    target = Thread(
        title="Target",
        format="Comic",
        issues_remaining=2,
        queue_position=2,
        status="active",
        user_id=user.id,
        is_blocked=True,  # stale flag
    )
    async_db.add_all([source, target])
    await async_db.flush()

    source_issue = Issue(thread_id=source.id, issue_number="1", position=1, status="unread")
    target_issue_1 = Issue(thread_id=target.id, issue_number="1", position=1, status="unread")
    target_issue_2 = Issue(thread_id=target.id, issue_number="2", position=2, status="unread")
    async_db.add_all([source_issue, target_issue_1, target_issue_2])
    await async_db.flush()

    source.next_unread_issue_id = source_issue.id
    target.next_unread_issue_id = target_issue_1.id  # next unread is #1
    # dependency only touches issue #2 — should NOT block reading issue #1
    async_db.add(Dependency(source_issue_id=source_issue.id, target_issue_id=target_issue_2.id))
    await async_db.commit()

    await async_db.refresh(target)
    assert target.is_blocked is True  # stale flag still set before refresh

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
