"""Regression coverage for transitive continuity prerequisite traversal."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.continuity_graph import load_snapshot as _load_snapshot
from app.models.continuity_rule import ContinuityRule
from app.models.issue import Issue
from app.models.thread import Thread
from tests.conftest import get_or_create_user_async


async def _make_issue(async_db: AsyncSession, *, user_id: int, suffix: str) -> Issue:
    """Create one active thread with one unread issue."""
    thread = Thread(
        title=f"Chain {suffix}",
        format="comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user_id,
        total_issues=1,
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.flush()
    thread.next_unread_issue_id = issue.id
    return issue


def _item_rule(*, user_id: int, source_id: int, target_id: int) -> ContinuityRule:
    """Create one issue-to-issue item-read rule."""
    return ContinuityRule(
        user_id=user_id,
        source_type="issue",
        source_id=source_id,
        target_type="issue",
        target_id=target_id,
        satisfaction_type="item_read",
    )


@pytest.mark.asyncio
async def test_snapshot_query_count_matches_bounded_queries(async_db: AsyncSession) -> None:
    """Snapshot query count matches the expected number of bounded queries."""
    user = await get_or_create_user_async(async_db)
    issue_a = await _make_issue(async_db, user_id=user.id, suffix="count-a")
    issue_b = await _make_issue(async_db, user_id=user.id, suffix="count-b")
    async_db.add(
        ContinuityRule(
            user_id=user.id,
            source_type="issue",
            source_id=issue_b.id,
            target_type="issue",
            target_id=issue_a.id,
            satisfaction_type="item_read",
        )
    )
    await async_db.commit()

    snapshot = await _load_snapshot(async_db, user.id)
    # 6 queries: threads, issues, groups, memberships, rules, selected_members
    assert snapshot.query_count == 6
    # At minimum we loaded the two threads, two issues, and one rule
    assert snapshot.rows_loaded >= 5


@pytest.mark.asyncio
async def test_snapshot_cache_is_per_user(async_db: AsyncSession) -> None:
    """Snapshot cache is keyed by user_id and does not leak across users."""
    user1 = await get_or_create_user_async(async_db, username="cache_test_user1")
    user2 = await get_or_create_user_async(async_db, username="cache_test_user2")
    issue1 = await _make_issue(async_db, user_id=user1.id, suffix="user1")
    issue2 = await _make_issue(async_db, user_id=user2.id, suffix="user2")
    await async_db.commit()

    snapshot1 = await _load_snapshot(async_db, user1.id)
    snapshot2 = await _load_snapshot(async_db, user2.id)

    assert snapshot1 is not snapshot2
    assert issue1.id in snapshot1.issues
    assert issue1.id not in snapshot2.issues
    assert issue2.id in snapshot2.issues
    assert issue2.id not in snapshot1.issues


@pytest.mark.asyncio
async def test_large_graph_query_count_does_not_grow_with_node_count(
    async_db: AsyncSession,
) -> None:
    """Query count stays constant (6) regardless of graph size within bounds."""
    user = await get_or_create_user_async(async_db)
    target = await _make_issue(async_db, user_id=user.id, suffix="growth-target")
    prerequisites = [
        await _make_issue(async_db, user_id=user.id, suffix=f"growth-{index}")
        for index in range(50)
    ]
    async_db.add_all(
        [
            ContinuityRule(
                user_id=user.id,
                source_type="issue",
                source_id=issue.id,
                target_type="issue",
                target_id=target.id,
                satisfaction_type="item_read",
            )
            for issue in prerequisites
        ]
    )
    await async_db.commit()

    snapshot = await _load_snapshot(async_db, user.id)
    # Query count should remain 6 even with 50 prerequisite issues
    assert snapshot.query_count == 6
    # Rows loaded grows with data but query count is bounded
    assert snapshot.rows_loaded >= 52  # 50 issues + target + at least 1 thread
