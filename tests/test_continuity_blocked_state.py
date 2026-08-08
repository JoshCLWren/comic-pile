"""Regression coverage for the unified Queue/Roll blocked-state projection."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.thread import Thread
from comic_pile.dependencies import (
    _get_blocked_thread_ids_uncached,
    refresh_user_blocked_status,
)
from tests.conftest import get_or_create_user_async


async def _make_thread_with_issue(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    queue_position: int,
) -> tuple[Thread, Issue]:
    thread = Thread(
        title=title,
        format="comic",
        issues_remaining=1,
        total_issues=1,
        queue_position=queue_position,
        status="active",
        user_id=user_id,
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
    await db.flush()
    return thread, issue


@pytest.mark.asyncio
async def test_continuity_rule_immediately_updates_denormalized_blocked_state(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    user = await get_or_create_user_async(async_db)
    source_thread, source_issue = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="Continuity source",
        queue_position=901,
    )
    target_thread, target_issue = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="Continuity target",
        queue_position=902,
    )
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/continuity-rules/",
        json={
            "source_type": "issue",
            "source_id": source_issue.id,
            "target_type": "issue",
            "target_id": target_issue.id,
            "satisfaction_type": "item_read",
            "selected_member_issue_ids": [],
        },
    )
    assert response.status_code == 201, response.text

    await async_db.refresh(target_thread)
    assert target_thread.is_blocked is True

    readiness_response = await auth_client.post(
        "/api/v1/continuity/readiness",
        json={"node_type": "thread", "node_id": target_thread.id},
    )
    assert readiness_response.status_code == 200
    assert readiness_response.json()["is_readable"] is False

    source_issue.status = "read"
    await async_db.flush()
    changes = await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()
    await async_db.refresh(target_thread)

    assert changes[target_thread.id] is True
    assert target_thread.is_blocked is False
    assert source_thread.is_blocked is False


@pytest.mark.asyncio
async def test_unified_blocked_ids_preserve_legacy_issue_dependencies(
    async_db: AsyncSession,
) -> None:
    user = await get_or_create_user_async(async_db)
    _legacy_source_thread, legacy_source_issue = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="Legacy source",
        queue_position=911,
    )
    legacy_target_thread, legacy_target_issue = await _make_thread_with_issue(
        async_db,
        user_id=user.id,
        title="Legacy target",
        queue_position=912,
    )
    async_db.add(
        Dependency(
            source_issue_id=legacy_source_issue.id,
            target_issue_id=legacy_target_issue.id,
        )
    )
    await async_db.commit()

    blocked_ids = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert legacy_target_thread.id in blocked_ids

    legacy_source_issue.status = "read"
    await async_db.commit()
    blocked_ids = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert legacy_target_thread.id not in blocked_ids
