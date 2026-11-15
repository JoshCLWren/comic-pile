"""Tests for batched issue dependency retrieval."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import Dependency, Issue, Thread, User


@pytest.mark.asyncio
async def test_list_thread_issue_dependencies_batches_edges(
    auth_client,
    async_db,
    test_username,
):
    """One request should return populated and empty issue dependency payloads."""
    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one()

    source_thread = Thread(
        title="Batch Source",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=2,
    )
    target_thread = Thread(
        title="Batch Target",
        format="Comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
        total_issues=1,
    )
    async_db.add_all([source_thread, target_thread])
    await async_db.flush()

    source_issue = Issue(
        thread_id=source_thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    empty_issue = Issue(
        thread_id=source_thread.id,
        issue_number="2",
        position=2,
        status="unread",
    )
    target_issue = Issue(
        thread_id=target_thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    async_db.add_all([source_issue, empty_issue, target_issue])
    await async_db.flush()

    source_thread.next_unread_issue_id = source_issue.id
    target_thread.next_unread_issue_id = target_issue.id
    dependency = Dependency(
        source_issue_id=source_issue.id,
        target_issue_id=target_issue.id,
    )
    async_db.add(dependency)
    await async_db.commit()

    response = await auth_client.get(
        f"/api/v1/threads/{source_thread.id}/issue-dependencies"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["thread_id"] == source_thread.id
    assert [item["issue_id"] for item in payload["issues"]] == [
        source_issue.id,
        empty_issue.id,
    ]

    source_payload = payload["issues"][0]
    assert source_payload["incoming"] == []
    assert source_payload["outgoing"] == [
        {
            "dependency_id": dependency.id,
            "source_issue_id": target_issue.id,
            "source_issue_number": "1",
            "source_thread_id": target_thread.id,
            "source_thread_title": "Batch Target",
        }
    ]
    assert payload["issues"][1] == {
        "issue_id": empty_issue.id,
        "incoming": [],
        "outgoing": [],
    }


@pytest.mark.asyncio
async def test_list_thread_issue_dependencies_enforces_ownership(
    auth_client,
    async_db,
):
    """The batch endpoint should not expose another user's thread."""
    outsider = User(username="batch_dependency_outsider", created_at=datetime.now(UTC))
    async_db.add(outsider)
    await async_db.flush()

    outsider_thread = Thread(
        title="Private Batch",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=outsider.id,
        total_issues=1,
    )
    async_db.add(outsider_thread)
    await async_db.flush()

    outsider_issue = Issue(
        thread_id=outsider_thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    async_db.add(outsider_issue)
    await async_db.flush()
    outsider_thread.next_unread_issue_id = outsider_issue.id
    await async_db.commit()

    response = await auth_client.get(
        f"/api/v1/threads/{outsider_thread.id}/issue-dependencies"
    )

    assert response.status_code == 404
