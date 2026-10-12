"""Tests for the all-users ``threads.is_blocked`` refresh (#3512).

``c25530000001`` changed Roll blocking to canonical Dependencies only but
left the denormalized flag stale. The follow-up refresh must:

* unblock threads held only by inert ``cbl-order:%`` edges or a
  ContinuityRule that mirrors one;
* cover every user, not just the caller;
* leave a still-canonical blocked thread blocked so Roll cannot pick it;
* make stored flags match ``_get_blocked_thread_ids_uncached``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.thread import Thread
from app.models.user import User
from app.services.blocked_flag_refresh import refresh_all_users_blocked_status_async
from comic_pile.dependencies import _get_blocked_thread_ids_uncached
from comic_pile.queue import get_roll_pool


async def _user(db: AsyncSession, username: str) -> User:
    """Insert a user for the refresh fixture."""
    user = User(username=username, created_at=datetime.now(UTC))
    db.add(user)
    await db.flush()
    return user


async def _thread_with_issue(
    db: AsyncSession,
    user_id: int,
    title: str,
    *,
    queue_position: int,
    is_blocked: bool,
) -> tuple[Thread, Issue]:
    """Insert an active thread whose frontier is a single unread issue."""
    thread = Thread(
        user_id=user_id,
        title=title,
        format="Comic",
        queue_position=queue_position,
        status="active",
        issues_remaining=1,
        total_issues=1,
        reading_progress="unstarted",
        is_blocked=is_blocked,
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    db.add(issue)
    await db.flush()
    thread.next_unread_issue_id = issue.id
    await db.flush()
    return thread, issue


async def _stored_flags(db: AsyncSession) -> dict[int, bool]:
    """Return every thread's stored blocked flag."""
    result = await db.execute(select(Thread.id, Thread.is_blocked))
    return {row.id: row.is_blocked for row in result.all()}


async def _assert_flags_match_evaluator(db: AsyncSession, user_ids: list[int]) -> None:
    """Assert stored flags equal the canonical evaluator for each user."""
    flags = await _stored_flags(db)
    for user_id in user_ids:
        blocked = await _get_blocked_thread_ids_uncached(user_id, db)
        owned = (
            await db.execute(select(Thread.id).where(Thread.user_id == user_id))
        ).all()
        for (thread_id,) in owned:
            assert flags[thread_id] is (thread_id in blocked)


@pytest.mark.asyncio
async def test_refresh_unblocks_inert_edges_for_all_users_and_keeps_canonical(
    async_db: AsyncSession,
) -> None:
    """Stale cbl-order / mirrored-rule flags clear for every user; canonical stays.

    User A has a thread blocked only by a ``cbl-order:%`` dependency plus a
    ContinuityRule that mirrors that edge. User B has the same stale
    cbl-order-only case. User A also has a still-canonical blocked thread.
    After the set-based refresh, stored flags match the evaluator, Roll
    includes the unblocked threads, and the canonical case stays out.
    """
    user_a = await _user(async_db, "blocked-refresh-a")
    user_b = await _user(async_db, "blocked-refresh-b")

    stale_source_a, stale_source_issue_a = await _thread_with_issue(
        async_db, user_a.id, "A Source", queue_position=1, is_blocked=False
    )
    stale_target_a, stale_target_issue_a = await _thread_with_issue(
        async_db, user_a.id, "A Stale CBL Target", queue_position=2, is_blocked=True
    )
    cbl_dep = Dependency(
        source_issue_id=stale_source_issue_a.id,
        target_issue_id=stale_target_issue_a.id,
        note="cbl-order:source:deadbeef:1",
    )
    async_db.add(cbl_dep)
    await async_db.flush()
    async_db.add(
        ContinuityRule(
            user_id=user_a.id,
            legacy_dependency_id=cbl_dep.id,
            source_type="issue",
            source_id=stale_source_issue_a.id,
            target_type="issue",
            target_id=stale_target_issue_a.id,
            satisfaction_type="item_read",
            note="cbl-order:source:deadbeef:1",
        )
    )

    canon_source_a, canon_source_issue_a = await _thread_with_issue(
        async_db, user_a.id, "A Canonical Source", queue_position=3, is_blocked=False
    )
    canon_target_a, canon_target_issue_a = await _thread_with_issue(
        async_db, user_a.id, "A Canonical Target", queue_position=4, is_blocked=True
    )
    async_db.add(
        Dependency(
            source_issue_id=canon_source_issue_a.id,
            target_issue_id=canon_target_issue_a.id,
            note=None,
        )
    )

    stale_source_b, stale_source_issue_b = await _thread_with_issue(
        async_db, user_b.id, "B Source", queue_position=1, is_blocked=False
    )
    stale_target_b, stale_target_issue_b = await _thread_with_issue(
        async_db, user_b.id, "B Stale CBL Target", queue_position=2, is_blocked=True
    )
    async_db.add(
        Dependency(
            source_issue_id=stale_source_issue_b.id,
            target_issue_id=stale_target_issue_b.id,
            note="cbl-order:source:cafe:2",
        )
    )
    await async_db.flush()

    changed = await refresh_all_users_blocked_status_async(async_db)
    assert changed[user_a.id] == 1
    assert changed[user_b.id] == 1
    assert set(changed) == {user_a.id, user_b.id}

    async_db.expire_all()
    await _assert_flags_match_evaluator(async_db, [user_a.id, user_b.id])

    flags = await _stored_flags(async_db)
    assert flags[stale_target_a.id] is False
    assert flags[stale_target_b.id] is False
    assert flags[canon_target_a.id] is True
    assert flags[stale_source_a.id] is False
    assert flags[canon_source_a.id] is False
    assert flags[stale_source_b.id] is False

    pool_a = {thread.id for thread in await get_roll_pool(user_a.id, async_db)}
    pool_b = {thread.id for thread in await get_roll_pool(user_b.id, async_db)}
    assert stale_target_a.id in pool_a
    assert canon_target_a.id not in pool_a
    assert stale_target_b.id in pool_b

    second = await refresh_all_users_blocked_status_async(async_db)
    assert second == {}
