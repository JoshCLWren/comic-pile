"""Regression tests for #2191: thread totals reflect adopted issue rows only.

Selective CBL materialization previously copied the external series volume size
into ``total_issues``/``issues_remaining`` while a thread owned only a subset of
the adopted issue rows. These tests pin the row-derived contract: totals, the
remaining-unread count, and the next-unread pointer always come from the issue
rows a thread actually owns.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread
from app.services.issue_tracking import derive_thread_issue_tracking_state
from tests.conftest import get_or_create_user_async


async def _declare_volume_thread(
    async_db: AsyncSession,
    *,
    user_id: int,
    title: str,
    external_total: int,
) -> Thread:
    """Create a thread carrying the external series size as its declared total.

    This mirrors the corrupted pre-fix materialization contract where the
    thread claimed to track the whole external volume while owning no rows yet.

    Args:
        async_db: Database session.
        user_id: Owning user id.
        title: Thread title.
        external_total: Declared external volume size.

    Returns:
        The persisted thread.
    """
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=external_total,
        queue_position=1,
        status="active",
        user_id=user_id,
        total_issues=external_total,
        reading_progress="not_started",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    return thread


@pytest.mark.asyncio
async def test_one_adopted_issue_does_not_inherit_external_volume_size(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A single adopted issue from a 20-issue volume yields total_issues of 1."""
    user = await get_or_create_user_async(async_db)
    thread = await _declare_volume_thread(
        async_db, user_id=user.id, title="Alpha Flight (1997)", external_total=20
    )

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "9"}
    )
    assert response.status_code == 201

    await async_db.refresh(thread)
    assert thread.total_issues == 1
    assert thread.issues_remaining == 1
    assert thread.next_unread_issue_id is not None
    assert thread.reading_progress == "not_started"

    result = await async_db.execute(select(Issue).where(Issue.thread_id == thread.id))
    owned = result.scalars().all()
    assert [issue.issue_number for issue in owned] == ["9"]


@pytest.mark.asyncio
async def test_non_contiguous_adopted_issues_do_not_inherit_external_volume_size(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Several non-contiguous adopted issues count only the adopted rows."""
    user = await get_or_create_user_async(async_db)
    thread = await _declare_volume_thread(
        async_db, user_id=user.id, title="Teen Titans (2005)", external_total=44
    )

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "35, 37"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["total_count"] == 2

    await async_db.refresh(thread)
    assert thread.total_issues == 2
    assert thread.issues_remaining == 2
    assert thread.reading_progress == "not_started"

    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    owned = result.scalars().all()
    assert [issue.issue_number for issue in owned] == ["35", "37"]


@pytest.mark.asyncio
async def test_derived_state_correct_immediately_after_persistence(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """First materialization derives totals, remaining, and next-unread at once."""
    user = await get_or_create_user_async(async_db)
    thread = Thread(
        title="New Series",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=None,
        reading_progress=None,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "1-3"}
    )
    assert response.status_code == 201

    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    owned = result.scalars().all()
    assert [issue.issue_number for issue in owned] == ["1", "2", "3"]

    await async_db.refresh(thread)
    assert thread.total_issues == 3
    assert thread.issues_remaining == 3
    assert thread.next_unread_issue_id == owned[0].id
    assert thread.reading_progress == "not_started"
    assert thread.status == "active"


@pytest.mark.asyncio
async def test_imported_thread_does_not_queue_omitted_external_issues(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Listed issues match the adopted rows; volume siblings are not owned."""
    user = await get_or_create_user_async(async_db)
    thread = await _declare_volume_thread(
        async_db, user_id=user.id, title="Wolverine (2005)", external_total=28
    )

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "900"}
    )
    assert response.status_code == 201

    listed = await auth_client.get(f"/api/v1/threads/{thread.id}/issues")
    assert listed.status_code == 200
    listed_data = listed.json()
    assert listed_data["total_count"] == 1
    assert [issue["issue_number"] for issue in listed_data["issues"]] == ["900"]

    await async_db.refresh(thread)
    assert thread.total_issues == 1
    assert thread.issues_remaining == 1


def test_derive_empty_issue_set_is_completed() -> None:
    """An issue set with no rows reports zero totals and completed progress."""
    state = derive_thread_issue_tracking_state([])
    assert state.total_issues == 0
    assert state.issues_remaining == 0
    assert state.next_unread_issue_id is None
    assert state.reading_progress == "completed"


def test_derive_partially_read_issue_set_is_in_progress() -> None:
    """A partially read set reports the earliest unread issue as next-unread."""
    issues = [
        Issue(id=1, thread_id=10, issue_number="1", position=1, status="read"),
        Issue(id=2, thread_id=10, issue_number="2", position=2, status="unread"),
        Issue(id=3, thread_id=10, issue_number="3", position=3, status="unread"),
    ]
    state = derive_thread_issue_tracking_state(issues)
    assert state.total_issues == 3
    assert state.issues_remaining == 2
    assert state.next_unread_issue_id == 2
    assert state.reading_progress == "in_progress"