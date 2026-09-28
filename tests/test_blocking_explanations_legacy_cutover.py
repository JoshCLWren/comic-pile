"""Blocking-explanation behavior after the canonical Dependency Roll cutover."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.thread import Thread
from comic_pile.dependencies import (
    format_blocking_reason,
    get_blocking_explanations,
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
async def test_blocking_explanations_use_canonical_dependencies(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Canonical Dependency blockers produce human-readable blocking reasons."""
    user = await get_or_create_user_async(async_db)
    source_thread, source_issue = await _thread_issue(
        async_db, user_id=user.id, title="Canonical Source", queue_position=1,
    )
    target_thread, target_issue = await _thread_issue(
        async_db, user_id=user.id, title="Canonical Target", queue_position=2,
    )
    await async_db.commit()
    async_db.add(Dependency(source_issue_id=source_issue.id, target_issue_id=target_issue.id))
    await async_db.commit()
    await async_db.refresh(target_thread)
    assert target_thread.is_blocked is True
    reasons = await get_blocking_explanations(target_thread.id, user.id, async_db)
    expected = "Blocked by Canonical Source: #1"
    assert [format_blocking_reason(dep) for dep in reasons] == [expected]
    source_issue.status = "read"
    source_issue.read_at = datetime.now(UTC)
    source_thread.next_unread_issue_id = None
    source_thread.issues_remaining = 0
    await async_db.flush()
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()
    await async_db.refresh(target_thread)
    assert target_thread.is_blocked is False
    assert get_blocking_explanations(target_thread.id, user.id, async_db) == []


@pytest.mark.asyncio
async def test_cbl_order_rows_do_not_produce_blocking_explanations(
    async_db: AsyncSession,
) -> None:
    """Historical cbl-order:% rows must not produce blocking explanations."""
    user = await get_or_create_user_async(async_db)
    source_thread, source_issue = await _thread_issue(
        async_db, user_id=user.id, title="CBL Source", queue_position=1,
    )
    target_thread, target_issue = await _thread_issue(
        async_db, user_id=user.id, title="CBL Target", queue_position=2,
    )
    async_db.add(Dependency(source_issue_id=source_issue.id, target_issue_id=target_issue.id, note="cbl-order:source:12345"))
    await async_db.commit()
    reasons = await get_blocking_explanations(target_thread.id, user.id, async_db)
    assert reasons == []


@pytest.mark.asyncio
async def test_canonical_dependency_blocks_correctly(
    async_db: AsyncSession,
) -> None:
    """Canonical Dependency rows (note=None) correctly block Roll."""
    user = await get_or_create_user_async(async_db)
    source_thread, source_issue = await _thread_issue(
        async_db, user_id=user.id, title="Source", queue_position=1,
    )
    target_thread, target_issue = await _thread_issue(
        async_db, user_id=user.id, title="Target", queue_position=2,
    )
    async_db.add(Dependency(source_issue_id=source_issue.id, target_issue_id=target_issue.id))
    await async_db.commit()
    from comic_pile.dependencies import _get_blocked_thread_ids_uncached
    blocked = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert target_thread.id in blocked
    source_issue.status = "read"
    await async_db.commit()
    blocked = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert target_thread.id not in blocked
