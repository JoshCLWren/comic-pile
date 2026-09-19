"""Blocking-explanation behavior after the Dependency-only Roll cutover."""

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
    update_thread_blocked_status,
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


async def _add_dependency(
    db: AsyncSession,
    source_issue: Issue,
    target_issue: Issue,
    *,
    note: str | None = None,
    commit: bool = True,
) -> Dependency:
    """Insert a raw Dependency edge like the legacy cutover rows in production."""
    dependency = Dependency(
        source_issue_id=source_issue.id,
        target_issue_id=target_issue.id,
        note=note,
    )
    db.add(dependency)
    if commit:
        await db.flush()
        await db.commit()
    return dependency


@pytest.mark.asyncio
async def test_blocking_explanations_use_canonical_dependencies(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Canonical Dependency edges still produce human-readable getBlockingInfo copy."""
    user = await get_or_create_user_async(async_db)
    source_thread, source_issue = await _thread_issue(
        async_db,
        user_id=user.id,
        title="Dependency Source",
        queue_position=1,
    )
    target_thread, target_issue = await _thread_issue(
        async_db,
        user_id=user.id,
        title="Dependency Target",
        queue_position=2,
    )
    await async_db.commit()
    await _add_dependency(async_db, source_issue, target_issue, note="preface")
    await update_thread_blocked_status(target_thread.id, user.id, async_db)
    await async_db.commit()
    await async_db.refresh(target_thread)
    assert target_thread.is_blocked is True

    reasons = await get_blocking_explanations(target_thread.id, user.id, async_db)
    batched = await get_blocking_explanations_batch([target_thread.id], user.id, async_db)
    expected = "Blocked by Dependency Source: #1"
    assert [format_blocking_reason(dep) for dep in reasons] == [expected]
    assert {
        thread_id: [format_blocking_reason(dep) for dep in deps]
        for thread_id, deps in batched.items()
    } == {target_thread.id: [expected]}

    response = await auth_client.post(
        f"/api/v1/threads/{target_thread.id}:getBlockingInfo"
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["is_blocked"] is True
    assert payload["blocking_reasons"] == [expected]
    assert payload["blocking_dependencies"][0]["thread_title"] == "Dependency Source"
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

    cleared_reasons = await get_blocking_explanations(target_thread.id, user.id, async_db)
    assert cleared_reasons == []
    cleared_batch = await get_blocking_explanations_batch(
        [target_thread.id], user.id, async_db
    )
    assert cleared_batch[target_thread.id] == []


@pytest.mark.asyncio
async def test_cbl_order_dependency_note_is_inert_for_blocking(
    async_db: AsyncSession,
) -> None:
    """cbl-order:% dependency rows are inert historical materialization, not blockers."""
    user = await get_or_create_user_async(async_db)
    source_thread, source_issue = await _thread_issue(
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
    await async_db.commit()
    await _add_dependency(
        async_db, source_issue, target_issue, note="cbl-order:materialized"
    )
    await async_db.refresh(target_thread)
    assert target_thread.is_blocked is False

    blocked = await dependencies._get_blocked_thread_ids_uncached(user.id, async_db)
    assert target_thread.id not in blocked
    assert await get_blocking_explanations(target_thread.id, user.id, async_db) == []


@pytest.mark.asyncio
async def test_legacy_off_ignores_sequence_order_even_after_unread_reactivation(
    async_db: AsyncSession,
) -> None:
    """Sequence-order-only dependency groups must not block Roll eligibility."""
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
    assert await get_blocking_explanations(later_thread.id, user.id, async_db) == []

    # Mark earlier read then unread again — sequence_order must stay non-authoritative.
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
