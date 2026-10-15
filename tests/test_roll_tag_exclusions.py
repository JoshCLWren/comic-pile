"""Tests for persistent account-wide tag exclusions in Roll eligibility."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tag, TagAssignment, Thread
from app.models.user import User
from tests.conftest import get_or_create_user_async


async def _thread_with_issue(
    db: AsyncSession, user: User, tag_id: int | None = None
) -> tuple[Thread, int]:
    thread = Thread(
        user_id=user.id,
        title="Tagged thread",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()

    from app.models.issue import Issue

    issue = Issue(thread_id=thread.id, issue_number="1", status="unread")
    db.add(issue)
    await db.flush()
    thread.next_unread_issue_id = issue.id
    await db.flush()

    if tag_id is not None:
        assignment = TagAssignment(tag_id=tag_id, target_type="Issue", target_id=issue.id)
        db.add(assignment)
        await db.flush()

    return thread, issue.id


@pytest.mark.asyncio
async def test_preferences_persist_excluded_tag_ids(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Excluded tag IDs persist through the preferences contract."""
    response = await auth_client.patch(
        "/api/v1/users/me/preferences", json={"excluded_tag_ids": [42, 7]}
    )
    assert response.status_code == 200
    assert sorted(response.json()["excluded_tag_ids"]) == [7, 42]

    follow_up = await auth_client.get("/api/v1/users/me/preferences")
    assert follow_up.status_code == 200
    assert sorted(follow_up.json()["excluded_tag_ids"]) == [7, 42]


@pytest.mark.asyncio
async def test_preferences_default_excluded_tag_ids_empty(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Users with no preferences row resolve to an empty exclusion list."""
    response = await auth_client.get("/api/v1/users/me/preferences")
    assert response.status_code == 200
    assert response.json()["excluded_tag_ids"] == []
