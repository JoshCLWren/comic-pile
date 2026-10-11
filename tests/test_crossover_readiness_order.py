"""Crossover reading-order persistence coverage.

Crossover ``sequence_order`` is presentation/provenance only (#2553): it is
persisted and returned by the reading-order-group endpoints, but it is not a
Roll blocking authority. Blocking comes solely from Thread frontiers plus
canonical Dependency rows.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.issue import Issue
from app.models.thread import Thread
from tests.conftest import get_or_create_user_async


async def _make_thread_with_issue(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    queue_position: int,
    issue_number: str = "1",
) -> tuple[Thread, Issue]:
    """Create one owned thread with a single unread issue."""
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
        issue_number=issue_number,
        position=1,
        status="unread",
    )
    db.add(issue)
    await db.flush()
    thread.next_unread_issue_id = issue.id
    await db.flush()
    return thread, issue


@pytest.mark.asyncio
async def test_reorder_endpoint_persists_reading_order(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """PUT /{group_id}/order persists the declared order for presentation."""
    user = await get_or_create_user_async(async_db)
    _first_thread, first_issue = await _make_thread_with_issue(
        async_db, user_id=user.id, title="Reorder first", queue_position=750
    )
    _second_thread, second_issue = await _make_thread_with_issue(
        async_db, user_id=user.id, title="Reorder second", queue_position=751
    )
    group = DependencyGroup(user_id=user.id, name="Reorder crossover")
    async_db.add(group)
    await async_db.flush()
    async_db.add(DependencyGroupMembership(group_id=group.id, issue_id=first_issue.id))
    async_db.add(DependencyGroupMembership(group_id=group.id, issue_id=second_issue.id))
    await async_db.commit()

    response = await auth_client.put(
        f"/api/v1/reading-order-groups/{group.id}/order",
        json={
            "items": [
                {"issue_id": first_issue.id, "sequence_order": 1},
                {"issue_id": second_issue.id, "sequence_order": 2},
            ]
        },
    )
    assert response.status_code == 200, response.text
    members_by_issue = {
        member["issue_id"]: member for member in response.json()["memberships"]
    }
    assert members_by_issue[first_issue.id]["sequence_order"] == 1
    assert members_by_issue[second_issue.id]["sequence_order"] == 2


@pytest.mark.asyncio
async def test_add_member_persists_sequence_order(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """POST member with sequence_order stores it and returns it in the response."""
    user = await get_or_create_user_async(async_db)
    _thread, issue = await _make_thread_with_issue(
        async_db, user_id=user.id, title="Ordered member", queue_position=752
    )
    group = DependencyGroup(user_id=user.id, name="Single ordered crossover")
    async_db.add(group)
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/reading-order-groups/{group.id}/members",
        json={"issue_id": issue.id, "sequence_order": 5},
    )
    assert response.status_code == 201, response.text
    assert response.json()["sequence_order"] == 5


@pytest.mark.asyncio
async def test_reorder_endpoint_rejects_member_duplicates(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """PUT /{group_id}/order rejects an issue listed twice."""
    user = await get_or_create_user_async(async_db)
    _thread, issue = await _make_thread_with_issue(
        async_db, user_id=user.id, title="Duplicate order", queue_position=753
    )
    group = DependencyGroup(user_id=user.id, name="Duplicate crossover")
    async_db.add(group)
    await async_db.flush()
    async_db.add(DependencyGroupMembership(group_id=group.id, issue_id=issue.id))
    await async_db.commit()

    response = await auth_client.put(
        f"/api/v1/reading-order-groups/{group.id}/order",
        json={
            "items": [
                {"issue_id": issue.id, "sequence_order": 1},
                {"issue_id": issue.id, "sequence_order": 2},
            ]
        },
    )
    assert response.status_code == 422, response.text
