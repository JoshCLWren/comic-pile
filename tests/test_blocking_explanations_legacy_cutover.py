"""Blocking-explanation behavior after the legacy Dependency Roll switch is off."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

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
async def test_blocking_explanations_use_continuity_when_legacy_switch_disabled(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Continuity-only blockers still produce human-readable getBlockingInfo copy."""
    user = await get_or_create_user_async(async_db)
    source_thread, source_issue = await _thread_issue(
        async_db,
        user_id=user.id,
        title="Continuity Source",
        queue_position=1,
    )
    target_thread, target_issue = await _thread_issue(
        async_db,
        user_id=user.id,
        title="Continuity Target",
        queue_position=2,
    )
    await async_db.commit()

    created = await auth_client.post(
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
    assert created.status_code == 201, created.text
    await async_db.refresh(target_thread)
    assert target_thread.is_blocked is True

    monkeypatch.setattr(
        dependencies,
        "get_app_settings",
        lambda: SimpleNamespace(legacy_dependency_blocking_enabled=False),
    )

    reasons = await get_blocking_explanations(target_thread.id, user.id, async_db)
    batched = await get_blocking_explanations_batch([target_thread.id], user.id, async_db)
    expected = "Blocked by Continuity Source: #1"
    assert [format_blocking_reason(dep) for dep in reasons] == [expected]
    assert {
        thread_id: [format_blocking_reason(dep) for dep in deps]
        for thread_id, deps in batched.items()
    } == {target_thread.id: [expected]}
    assert all(str(source_thread.id) not in reason for reason in [expected])

    response = await auth_client.post(
        f"/api/v1/threads/{target_thread.id}:getBlockingInfo"
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["is_blocked"] is True
    assert payload["blocking_reasons"] == [expected]
    assert payload["blocking_dependencies"][0]["thread_title"] == "Continuity Source"
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
