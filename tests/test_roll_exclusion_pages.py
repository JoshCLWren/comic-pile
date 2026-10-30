"""Paginated Roll exclusion drill-down for issue #3330.

The Roll UI shows bounded blocked and out-of-pool previews. The production
report was that the collapsed headings displayed the preview size (20) as if
it were the category total, and there was no way to reach the rest of the
category.

These tests drive the real endpoint against async PostgreSQL so the category
predicates are exercised against real rows. They pin the invariant the UI now
relies on: the drill-down total is the true category total for the same scope,
and every counted row is reachable by paging.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ReadingSession
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
async def test_blocked_category_total_and_pages_reach_every_series(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A 25-series blocked category is counted and reached without truncation."""
    user = await get_or_create_user_async(async_db)
    blocked = [
        await _thread(async_db, user.id, title=f"Blocked {index:02d}", position=index, is_blocked=True)
        for index in range(1, 26)
    ]
    await async_db.commit()

    first = await _exclusion_page(auth_client, category="blocked")
    assert first.category == "blocked"
    assert first.total == 25
    assert first.limit == 20
    assert first.offset == 0
    assert len(first.items) == 20
    assert first.next_cursor == "20"
    assert [item.thread_id for item in first.items] == [thread.id for thread in blocked[:20]]
    assert all(item.reason == "blocked" for item in first.items)

    second = await _exclusion_page(auth_client, category="blocked", offset=int(first.next_cursor))
    assert second.total == 25
    assert len(second.items) == 5
    assert second.next_cursor is None
    assert [item.thread_id for item in second.items] == [thread.id for thread in blocked[20:]]
    # Deterministic ordering across the boundary: no duplicates, no gaps.
    assert len({item.thread_id for item in [*first.items, *second.items]}) == 25
    assert blocked[-1].id in {item.thread_id for item in second.items}


@pytest.mark.asyncio
async def test_inactive_category_total_and_pages_reach_every_series(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A 26-series out-of-pool category is counted and reached across pages."""
    user = await get_or_create_user_async(async_db)
    completed = [
        await _thread(
            async_db,
            user.id,
            title=f"Completed {index:02d}",
            position=10 + index,
            status="completed",
        )
        for index in range(1, 14)
    ]
    deprioritized = [
        await _thread(async_db, user.id, title=f"Not queued {index:02d}", position=0)
        for index in range(1, 14)
    ]
    await async_db.commit()

    first = await _exclusion_page(auth_client, category="inactive")
    assert first.category == "inactive"
    assert first.total == 26
    assert len(first.items) == 20
    assert first.next_cursor == "20"

    second = await _exclusion_page(auth_client, category="inactive", offset=20)
    assert second.total == 26
    assert len(second.items) == 6
    assert second.next_cursor is None

    reached = [*first.items, *second.items]
    assert len({item.thread_id for item in reached}) == 26
    expected = {thread.id for thread in [*deprioritized, *completed]}
    assert {item.thread_id for item in reached} == expected
    reasons = {item.thread_id: item.reason for item in reached}
    for thread in completed:
        assert reasons[thread.id] == "completed"
        assert next(item.detail for item in reached if item.thread_id == thread.id) == (
            "Read the full series"
        )
    for thread in deprioritized:
        assert reasons[thread.id] == "not_in_queue"


@pytest.mark.asyncio
async def test_categories_below_the_preview_limit_are_complete_on_one_page(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Totals of 20 or fewer still report the true total and exhaust in one page."""
    user = await get_or_create_user_async(async_db)
    blocked = await _thread(async_db, user.id, title="Blocked", position=1, is_blocked=True)
    completed = await _thread(
        async_db, user.id, title="Completed", position=2, status="completed"
    )
    await async_db.commit()

    blocked_page = await _exclusion_page(auth_client, category="blocked")
    assert blocked_page.total == 1
    assert [item.thread_id for item in blocked_page.items] == [blocked.id]
    assert blocked_page.next_cursor is None

    inactive_page = await _exclusion_page(auth_client, category="inactive")
    assert inactive_page.total == 1
    assert [item.thread_id for item in inactive_page.items] == [completed.id]
    assert inactive_page.next_cursor is None


@pytest.mark.asyncio
async def test_exclusion_categories_partition_without_overlap(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Blocked, inactive, snoozed, and skipped populations never double count."""
    user = await get_or_create_user_async(async_db)
    available = await _thread(async_db, user.id, title="Available", position=1)
    blocked = await _thread(async_db, user.id, title="Blocked", position=2, is_blocked=True)
    snoozed = await _thread(async_db, user.id, title="Snoozed", position=3)
    skipped = await _thread(async_db, user.id, title="Skipped", position=4)
    deprioritized = await _thread(async_db, user.id, title="Deprioritized", position=0)
    completed = await _thread(
        async_db, user.id, title="Completed", position=5, status="completed"
    )
    await async_db.commit()

    async_db.add(
        ReadingSession(
            start_die=6,
            user_id=user.id,
            snoozed_thread_ids=[snoozed.id],
            skipped_thread_ids=[skipped.id],
        )
    )
    await async_db.commit()

    blocked_page = await _exclusion_page(auth_client, category="blocked")
    inactive_page = await _exclusion_page(auth_client, category="inactive")

    blocked_ids = {item.thread_id for item in blocked_page.items}
    inactive_ids = {item.thread_id for item in inactive_page.items}

    assert blocked_page.total == 1
    assert inactive_page.total == 2
    assert blocked_ids == {blocked.id}
    assert inactive_ids == {deprioritized.id, completed.id}
    assert blocked_ids.isdisjoint(inactive_ids)
    assert blocked_ids.isdisjoint({snoozed.id, skipped.id})
    assert inactive_ids.isdisjoint({snoozed.id, skipped.id})
    assert available.id not in blocked_ids | inactive_ids


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
async def test_inactive_page_uses_the_session_that_carries_pending_work(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """The drill-down resolves the same session that owns pending reading work.

    Two unended sessions can exist at once. The authoritative one still carries
    pending reading work, while the newest unended session may carry none.
    Reading the newest one here would classify a snoozed series as out-of-pool
    and disagree with the heading the UI renders beside it (#3330).
    """
    user = await get_or_create_user_async(async_db)
    # Both series sit outside the active queue, so the only thing that keeps
    # the snoozed one out of the out-of-pool category is the session.
    snoozed = await _thread(async_db, user.id, title="Snoozed", position=0)
    deprioritized = await _thread(async_db, user.id, title="Not queued", position=0)
    pending = await _thread(async_db, user.id, title="Pending", position=2)
    await async_db.commit()

    now = datetime.now(UTC)
    # The older session still carries pending reading work, so it stays the
    # authoritative current session even though a newer one exists.
    async_db.add(
        ReadingSession(
            start_die=6,
            user_id=user.id,
            started_at=now - timedelta(minutes=5),
            pending_thread_id=pending.id,
            pending_thread_updated_at=now - timedelta(minutes=5),
            snoozed_thread_ids=[snoozed.id],
        )
    )
    await async_db.flush()
    async_db.add(
        ReadingSession(
            start_die=6,
            user_id=user.id,
            started_at=now,
        )
    )
    await async_db.commit()

    inactive_page = await _exclusion_page(auth_client, category="inactive")

    # The snoozed series stays excluded instead of being reclassified as
    # out-of-pool because the endpoint read the other session.
    assert inactive_page.total == 1
    assert [item.thread_id for item in inactive_page.items] == [deprioritized.id]
    assert snoozed.id not in {item.thread_id for item in inactive_page.items}


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
