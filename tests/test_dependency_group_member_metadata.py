"""Focused coverage for enriched crossover member display metadata.

Issue #1658: crossover member lists must expose series titles and issue
numbers server-side so the UI never renders raw database IDs.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread, User
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership


def _unique_name(prefix: str) -> str:
    """Build a collision-free group name for repeatable test runs."""
    return f"{prefix} {uuid.uuid4().hex[:8]}"


async def _make_thread(
    db: AsyncSession,
    user: User,
    *,
    title: str,
    issue_count: int,
    queue_position: int,
) -> tuple[Thread, list[Issue]]:
    """Create an owned thread with contiguous issues."""
    thread = Thread(
        user_id=user.id,
        title=title,
        format="Comic",
        issues_remaining=issue_count,
        total_issues=issue_count,
        queue_position=queue_position,
        status="active",
    )
    db.add(thread)
    await db.flush()
    issues = []
    for position in range(1, issue_count + 1):
        issue = Issue(
            thread_id=thread.id,
            issue_number=str(position),
            position=position,
            status="unread",
        )
        db.add(issue)
        issues.append(issue)
    await db.flush()
    return thread, issues


@pytest.mark.asyncio
async def test_list_groups_enriches_both_membership_kinds(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Listed members carry the series title plus issue number when exact."""
    thread, issues = await _make_thread(
        async_db, default_user, title="Animal Man", issue_count=3, queue_position=90
    )
    group = DependencyGroup(user_id=default_user.id, name="Vertigo Crossover")
    async_db.add(group)
    await async_db.flush()
    async_db.add(DependencyGroupMembership(group_id=group.id, issue_id=issues[0].id))
    async_db.add(DependencyGroupMembership(group_id=group.id, thread_id=thread.id))
    await async_db.commit()

    response = await auth_client.get("/api/v1/reading-order-groups/")
    assert response.status_code == 200

    groups = {entry["name"]: entry for entry in response.json()}
    members = groups["Vertigo Crossover"]["memberships"]
    by_issue = {member["id"]: member for member in members}
    enriched = list(by_issue.values())

    issue_member = next(member for member in enriched if member["issue_id"] is not None)
    assert issue_member["series_title"] == "Animal Man"
    assert issue_member["issue_number"] == "1"

    thread_member = next(member for member in enriched if member["thread_id"] is not None)
    assert thread_member["series_title"] == "Animal Man"
    assert thread_member["issue_number"] is None


@pytest.mark.asyncio
async def test_add_member_returns_enriched_payload(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """The add-member response resolves comic metadata without a refetch."""
    thread, issues = await _make_thread(
        async_db, default_user, title="Starman", issue_count=2, queue_position=91
    )
    group = DependencyGroup(user_id=default_user.id, name="Space City")
    async_db.add(group)
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/reading-order-groups/{group.id}/members",
        json={"issue_id": issues[1].id},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["issue_id"] == issues[1].id
    assert payload["series_title"] == "Starman"
    assert payload["issue_number"] == "2"

    follow_up = await auth_client.get(f"/api/v1/reading-order-groups/{group.id}")
    assert follow_up.status_code == 200
    assert follow_up.json()["memberships"][0]["series_title"] == "Starman"
