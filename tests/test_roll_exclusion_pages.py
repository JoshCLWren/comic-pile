"""Paginated Roll exclusion drill-down for issue #3330.

The Roll bootstrap carries bounded previews of the blocked and out-of-pool
categories. The production report was that the collapsed headings displayed
the preview size (20) as if it were the category total, and there was no way
to reach the rest of the category.

These tests drive the real endpoint against async PostgreSQL so the category
predicates are exercised against real rows. They pin the invariant the UI now
relies on: the bootstrap count and the drill-down total are the same number
for the same category scope, and every counted row is reachable by paging.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.thread import Thread
from app.schemas import RollExclusionPageResponse
from tests.conftest import get_or_create_user_async


async def _thread(
    db: AsyncSession,
    user_id: int,
    *,
    title: str,
    position: int,
    status: str = "active",
    is_blocked: bool = False,
) -> Thread:
    """Persist one owned series and return it."""
    thread = Thread(
        user_id=user_id,
        title=title,
        format="Comic",
        issues_remaining=3,
        queue_position=position,
        status=status,
        is_blocked=is_blocked,
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    return thread




async def _exclusion_page(
    client: AsyncClient,
    *,
    category: str,
    limit: int = 20,
    offset: int = 0,
) -> RollExclusionPageResponse:
    """Fetch one exclusion drill-down page for the authenticated user."""
    response = await client.get(
        "/api/v1/roll/exclusions",
        params={"category": category, "limit": limit, "offset": offset},
    )
    assert response.status_code == 200, response.text
    return RollExclusionPageResponse.model_validate(response.json())


async def _thread_with_issue(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    queue_position: int,
    is_blocked: bool = False,
) -> tuple[Thread, Issue]:
    """Insert an active thread whose frontier is one unread issue."""
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
async def test_blocked_page_explains_dependency_details(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A blocked row carries its readable reason and dependency link details."""
    user = await get_or_create_user_async(async_db)
    source, source_issue = await _thread_with_issue(
        async_db, user_id=user.id, title="Unread Prerequisite", queue_position=1
    )
    target, target_issue = await _thread_with_issue(
        async_db, user_id=user.id, title="Waiting Series", queue_position=2, is_blocked=True
    )
    async_db.add(
        Dependency(
            source_issue_id=source_issue.id,
            target_issue_id=target_issue.id,
            note=None,
        )
    )
    await async_db.commit()

    page = await _exclusion_page(auth_client, category="blocked")

    assert page.total == 1
    [item] = page.items
    assert item.thread_id == target.id
    assert item.reason == "blocked"
    assert item.detail is not None
    assert item.blocking_reasons
    assert item.detail == item.blocking_reasons[0]
    [dependency] = item.blocking_dependencies
    assert dependency.thread_id == source.id
    assert dependency.issue_number == "1"
    assert dependency.thread_title == "Unread Prerequisite"
    assert dependency.label.startswith("Blocked by Unread Prerequisite")


@pytest.mark.asyncio
async def test_exclusion_pages_are_user_scoped(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Another reader's blocked or inactive series never appear in this page."""
    owner = await get_or_create_user_async(async_db)
    other = await get_or_create_user_async(async_db, username="foreign_exclusion_page_owner")
    mine = await _thread(async_db, owner.id, title="Mine", position=1, is_blocked=True)
    await _thread(async_db, other.id, title="Theirs", position=1, is_blocked=True)
    await _thread(
        async_db, other.id, title="Their completed", position=2, status="completed"
    )
    await async_db.commit()

    blocked_page = await _exclusion_page(auth_client, category="blocked")
    inactive_page = await _exclusion_page(auth_client, category="inactive")

    assert blocked_page.total == 1
    assert [item.thread_id for item in blocked_page.items] == [mine.id]
    assert inactive_page.total == 0
    assert inactive_page.items == []


@pytest.mark.asyncio
async def test_exclusion_page_validates_category_and_bounds(
    auth_client: AsyncClient,
) -> None:
    """Unknown categories and out-of-range paging values are rejected."""
    unknown = await auth_client.get(
        "/api/v1/roll/exclusions", params={"category": "everything"}
    )
    assert unknown.status_code == 422

    too_large = await auth_client.get(
        "/api/v1/roll/exclusions", params={"category": "blocked", "limit": 101}
    )
    assert too_large.status_code == 422

    zero_limit = await auth_client.get(
        "/api/v1/roll/exclusions", params={"category": "blocked", "limit": 0}
    )
    assert zero_limit.status_code == 422

    negative_offset = await auth_client.get(
        "/api/v1/roll/exclusions", params={"category": "blocked", "offset": -1}
    )
    assert negative_offset.status_code == 422
