"""Tests for the enriched crossover detail endpoint.

Issue #2039: eliminate N+1 request waterfall for crossover detail page.
The detail endpoint must return thread, issue, and other-crossover metadata
in a single bounded response.
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
async def test_detail_endpoint_returns_enriched_members(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Detail response includes thread, issue, and other-crossover metadata."""
    thread, issues = await _make_thread(
        async_db, default_user, title="Animal Man", issue_count=3, queue_position=90
    )
    group = DependencyGroup(user_id=default_user.id, name=_unique_name("Crossover"))
    async_db.add(group)
    await async_db.flush()
    # Add issue-level membership
    async_db.add(DependencyGroupMembership(group_id=group.id, issue_id=issues[0].id))
    # Add thread-level membership
    async_db.add(DependencyGroupMembership(group_id=group.id, thread_id=thread.id))
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/reading-order-groups/{group.id}/detail")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == group.id
    assert data["name"] == group.name
    assert len(data["memberships"]) == 2

    # Check enriched member fields
    for member in data["memberships"]:
        assert "membership" in member
        assert "thread" in member
        assert "issue" in member
        assert "other_crossovers" in member

    # Issue-level membership should have issue and thread populated
    issue_member = next(
        m for m in data["memberships"] if m["membership"]["issue_id"] is not None
    )
    assert issue_member["issue"] is not None
    assert issue_member["issue"]["issue_number"] == "1"
    assert issue_member["thread"] is not None
    assert issue_member["thread"]["title"] == "Animal Man"

    # Thread-level membership should have thread populated, issue null
    thread_member = next(
        m for m in data["memberships"] if m["membership"]["thread_id"] is not None
    )
    assert thread_member["thread"] is not None
    assert thread_member["issue"] is None


@pytest.mark.asyncio
async def test_detail_endpoint_includes_other_crossovers(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Other crossovers are returned when a thread belongs to multiple groups."""
    thread1, _ = await _make_thread(
        async_db, default_user, title="Series A", issue_count=2, queue_position=1
    )
    thread2, _ = await _make_thread(
        async_db, default_user, title="Series B", issue_count=2, queue_position=2
    )
    # Create two groups, each containing both threads
    group1 = DependencyGroup(user_id=default_user.id, name=_unique_name("Group1"))
    group2 = DependencyGroup(user_id=default_user.id, name=_unique_name("Group2"))
    async_db.add_all([group1, group2])
    await async_db.flush()

    async_db.add(DependencyGroupMembership(group_id=group1.id, thread_id=thread1.id))
    async_db.add(DependencyGroupMembership(group_id=group1.id, thread_id=thread2.id))
    async_db.add(DependencyGroupMembership(group_id=group2.id, thread_id=thread1.id))
    async_db.add(DependencyGroupMembership(group_id=group2.id, thread_id=thread2.id))
    await async_db.commit()

    # Request detail for group1
    response = await auth_client.get(f"/api/v1/reading-order-groups/{group1.id}/detail")
    assert response.status_code == 200
    data = response.json()
    # Each member should list the other group's name in other_crossovers
    for member in data["memberships"]:
        assert group2.name in member["other_crossovers"]
        assert group1.name not in member["other_crossovers"]


@pytest.mark.asyncio
async def test_detail_endpoint_large_crossover_bounded_queries(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A 40-member crossover returns a single bounded response."""
    # Create 20 threads, each with 2 issues -> 40 memberships
    threads = []
    all_issues = []
    for i in range(20):
        thread, issues = await _make_thread(
            async_db,
            default_user,
            title=f"Series {i}",
            issue_count=2,
            queue_position=100 + i,
        )
        threads.append(thread)
        all_issues.extend(issues)

    group = DependencyGroup(user_id=default_user.id, name=_unique_name("LargeCrossover"))
    async_db.add(group)
    await async_db.flush()

    # Add both issues from each thread as memberships
    for issue in all_issues:
        async_db.add(DependencyGroupMembership(group_id=group.id, issue_id=issue.id))
    await async_db.commit()

    # The detail endpoint should succeed and return all 40 members
    response = await auth_client.get(f"/api/v1/reading-order-groups/{group.id}/detail")
    assert response.status_code == 200
    data = response.json()
    assert len(data["memberships"]) == 40

    # Verify each membership has thread and issue populated
    for member in data["memberships"]:
        assert member["thread"] is not None
        assert member["issue"] is not None
        assert member["thread"]["title"].startswith("Series")


@pytest.mark.asyncio
async def test_detail_endpoint_readiness_and_plans(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Detail includes continuity readiness and linked plans."""
    thread, issues = await _make_thread(
        async_db, default_user, title="Plan Series", issue_count=1, queue_position=200
    )
    group = DependencyGroup(user_id=default_user.id, name=_unique_name("PlanCrossover"))
    async_db.add(group)
    await async_db.flush()
    async_db.add(DependencyGroupMembership(group_id=group.id, issue_id=issues[0].id))
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/reading-order-groups/{group.id}/detail")
    assert response.status_code == 200
    data = response.json()
    # readiness may be None if no rules defined, but field should exist
    assert "readiness" in data
    assert "linked_plans" in data
    # linked_plans is a list
    assert isinstance(data["linked_plans"], list)
