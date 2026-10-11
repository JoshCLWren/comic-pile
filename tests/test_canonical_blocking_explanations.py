"""Blocking explanations under the canonical Roll runtime (#2553).

Explanations come from the same canonical Dependency authority as Roll
eligibility: Thread frontiers plus incoming Dependency rows whose note is NULL
or does not start with ``cbl-order:``. Historical CBL materialization and
crossover ``sequence_order`` never block and never explain.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.thread import Thread
from comic_pile import dependencies
from comic_pile.dependencies import (
    format_blocking_reason,
    get_blocking_explanations,
    get_blocking_explanations_batch,
    refresh_user_blocked_status,
)
from tests.conftest import get_or_create_user_async


async def _thread_issue(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    queue_position: int,
) -> tuple[Thread, Issue]:
    thread = Thread(
        user_id=user_id,
        title=title,
        format="comic",
        queue_position=queue_position,
        status="active",
        total_issues=1,
        issues_remaining=1,
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    issue = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    db.add(issue)
    await db.flush()
    thread.next_unread_issue_id = issue.id
    return thread, issue


@pytest.mark.asyncio
async def test_canonical_dependency_blocks_explains_and_clears(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A canonical edge blocks, explains, and clears when the source is read."""
    user = await get_or_create_user_async(async_db)
    source_thread, source_issue = await _thread_issue(
        async_db,
        user_id=user.id,
        title="Canonical Source",
        queue_position=1,
    )
    target_thread, target_issue = await _thread_issue(
        async_db,
        user_id=user.id,
        title="Canonical Target",
        queue_position=2,
    )
    async_db.add(
        Dependency(
            source_issue_id=source_issue.id,
            target_issue_id=target_issue.id,
            note="genuine prerequisite",
        )
    )
    await async_db.commit()

    await refresh_user_blocked_status(user.id, async_db)
    await async_db.refresh(target_thread)
    assert target_thread.is_blocked is True

    expected = "Blocked by Canonical Source: #1"
    reasons = await get_blocking_explanations(target_thread.id, user.id, async_db)
    assert [format_blocking_reason(dep) for dep in reasons] == [expected]
    batched = await get_blocking_explanations_batch([target_thread.id], user.id, async_db)
    assert {
        thread_id: [format_blocking_reason(dep) for dep in deps]
        for thread_id, deps in batched.items()
    } == {target_thread.id: [expected]}

    response = await auth_client.post(f"/api/v1/threads/{target_thread.id}:getBlockingInfo")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["is_blocked"] is True
    assert payload["blocking_reasons"] == [expected]
    assert payload["blocking_dependencies"][0]["thread_title"] == "Canonical Source"
    assert payload["blocking_dependencies"][0]["issue_number"] == "1"

    source_issue.status = "read"
    source_issue.read_at = datetime.now(UTC)
    source_thread.next_unread_issue_id = None
    source_thread.issues_remaining = 0
    await async_db.flush()
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()
    await async_db.refresh(target_thread)
    assert target_thread.is_blocked is False

    assert await get_blocking_explanations(target_thread.id, user.id, async_db) == []
    cleared_batch = await get_blocking_explanations_batch(
        [target_thread.id], user.id, async_db
    )
    assert cleared_batch[target_thread.id] == []


@pytest.mark.asyncio
async def test_cbl_order_rows_never_block_or_explain(async_db: AsyncSession) -> None:
    """Historical CBL materialization rows are inert for eligibility and copy."""
    user = await get_or_create_user_async(async_db)
    _source_thread, source_issue = await _thread_issue(
        async_db,
        user_id=user.id,
        title="CBL Source",
        queue_position=1,
    )
    target_thread, target_issue = await _thread_issue(
        async_db,
        user_id=user.id,
        title="CBL Target",
        queue_position=2,
    )
    async_db.add(
        Dependency(
            source_issue_id=source_issue.id,
            target_issue_id=target_issue.id,
            note="cbl-order:source:Some List",
        )
    )
    await async_db.commit()

    blocked = await dependencies._get_blocked_thread_ids_uncached(user.id, async_db)
    assert target_thread.id not in blocked
    assert await get_blocking_explanations(target_thread.id, user.id, async_db) == []


@pytest.mark.asyncio
async def test_sequence_order_never_blocks(async_db: AsyncSession) -> None:
    """Crossover sequence_order is presentation only, never a blocking authority."""
    from app.models.dependency_group import DependencyGroup, DependencyGroupMembership

    user = await get_or_create_user_async(async_db)
    earlier_thread, earlier_issue = await _thread_issue(
        async_db,
        user_id=user.id,
        title="Earlier ordered",
        queue_position=1,
    )
    later_thread, later_issue = await _thread_issue(
        async_db,
        user_id=user.id,
        title="Later ordered",
        queue_position=2,
    )
    group = DependencyGroup(user_id=user.id, name="Sequence order only")
    async_db.add(group)
    await async_db.flush()
    async_db.add_all(
        [
            DependencyGroupMembership(
                group_id=group.id,
                issue_id=earlier_issue.id,
                sequence_order=1,
            ),
            DependencyGroupMembership(
                group_id=group.id,
                issue_id=later_issue.id,
                sequence_order=2,
            ),
        ]
    )
    await async_db.commit()

    blocked = await dependencies._get_blocked_thread_ids_uncached(user.id, async_db)
    assert later_thread.id not in blocked
    assert earlier_thread.id not in blocked
    assert await get_blocking_explanations(later_thread.id, user.id, async_db) == []

    # Mark earlier read then unread again — sequence_order stays non-authoritative.
    earlier_issue.status = "read"
    earlier_issue.read_at = datetime.now(UTC)
    earlier_thread.next_unread_issue_id = None
    await async_db.flush()
    earlier_issue.status = "unread"
    earlier_issue.read_at = None
    earlier_thread.next_unread_issue_id = earlier_issue.id
    await async_db.commit()

    reactivated = await dependencies._get_blocked_thread_ids_uncached(user.id, async_db)
    assert later_thread.id not in reactivated
    assert await get_blocking_explanations(later_thread.id, user.id, async_db) == []


@pytest.mark.asyncio
async def test_explanations_agree_with_eligibility(async_db: AsyncSession) -> None:
    """Every blocked thread has an explanation; no unblocked thread does."""
    user = await get_or_create_user_async(async_db)
    _source_thread, source_issue = await _thread_issue(
        async_db,
        user_id=user.id,
        title="Explanation Source",
        queue_position=1,
    )
    blocked_thread, blocked_issue = await _thread_issue(
        async_db,
        user_id=user.id,
        title="Blocked Target",
        queue_position=2,
    )
    free_thread, _free_issue = await _thread_issue(
        async_db,
        user_id=user.id,
        title="Free Target",
        queue_position=3,
    )
    async_db.add(
        Dependency(
            source_issue_id=source_issue.id,
            target_issue_id=blocked_issue.id,
        )
    )
    await async_db.commit()

    blocked = await dependencies._get_blocked_thread_ids_uncached(user.id, async_db)
    assert blocked == {blocked_thread.id}

    explanations = await get_blocking_explanations_batch(
        [blocked_thread.id, free_thread.id], user.id, async_db
    )
    assert len(explanations[blocked_thread.id]) == 1
    assert explanations[free_thread.id] == []
