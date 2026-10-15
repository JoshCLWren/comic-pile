"""Regression tests for GET /api/v1/identity-inbox list performance.

Covers the N+1 query fix in list_inbox_items: ExternalIdentity must be
eager-loaded in the base query so the per-mapping db.get() calls are identity
map hits instead of separate round trips. Without this fix each mapping
triggers an additional ExternalIdentity lookup, scaling query count with
result set size and blowing the 1000 ms route budget.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.auth import create_access_token
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
)
from app.models.issue import Issue
from app.models.thread import Thread
from app.models.user import User
from app.services.identity_inbox import list_inbox_items


async def _user(async_db, username: str = "inbox_user") -> User:
    result = await async_db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(username=username)
        async_db.add(user)
        await async_db.flush()
        await async_db.refresh(user)
    return user


async def _thread(async_db, user_id: int, title: str) -> Thread:
    from sqlalchemy import func as _func

    max_pos = (
        await async_db.execute(select(_func.max(Thread.queue_position)).where(Thread.user_id == user_id))
    ).scalar() or 0
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=0,
        queue_position=max_pos + 1,
        status="active",
        user_id=user_id,
    )
    async_db.add(thread)
    await async_db.flush()
    await async_db.refresh(thread)
    return thread


async def _issue(async_db, thread_id: int, number: str) -> Issue:
    issue = Issue(
        thread_id=thread_id,
        issue_number=number,
        position=1,
        status="unread",
    )
    async_db.add(issue)
    await async_db.flush()
    await async_db.refresh(issue)
    return issue


async def _identity(async_db, provider: str, external_id: str) -> ExternalIdentity:
    identity = ExternalIdentity(
        provider=provider,
        entity_type="issue",
        external_id=external_id,
        metadata_json={"volume": {"name": "Test Volume"}, "publisher": "Test Publisher"},
    )
    async_db.add(identity)
    await async_db.flush()
    await async_db.refresh(identity)
    return identity


async def _mapping(
    async_db,
    issue_id: int,
    external_identity_id: int,
    status: str = "unresolved",
) -> IssueExternalIdentityMapping:
    mapping = IssueExternalIdentityMapping(
        issue_id=issue_id,
        external_identity_id=external_identity_id,
        status=status,
        evidence_source="test",
        confidence=0.5,
    )
    async_db.add(mapping)
    await async_db.flush()
    await async_db.refresh(mapping)
    return mapping


@pytest.mark.asyncio
async def test_list_inbox_items_returns_correct_fields(async_db) -> None:
    """list_inbox_items populates every IdentityInboxItem field from the joined query."""
    user = await _user(async_db)
    thread = await _thread(async_db, user.id, "Inbox Thread")
    issue = await _issue(async_db, thread.id, "1")
    identity = await _identity(async_db, "comicvine", "12345")
    await _mapping(async_db, issue.id, identity.id, status="unresolved")

    items, total = await list_inbox_items(async_db, user_id=user.id)

    assert total == 1
    assert len(items) == 1
    item = items[0]
    assert item.mapping_id is not None
    assert item.issue_id == issue.id
    assert item.thread_id == thread.id
    assert item.thread_title == "Inbox Thread"
    assert item.issue_number == "1"
    assert item.status == "unresolved"
    assert item.provider == "comicvine"
    assert item.source_entry_summary == "Inbox Thread #1 (Test Volume) - Test Publisher"
    assert item.candidates == []
    assert item.created_at is not None
    assert item.updated_at is not None


@pytest.mark.asyncio
async def test_list_inbox_items_scoped_to_user(async_db) -> None:
    """list_inbox_items only returns mappings belonging to the given user."""
    user_a = await _user(async_db, username="inbox_user_a")
    user_b = await _user(async_db, username="inbox_user_b")

    thread_a = await _thread(async_db, user_a.id, "Thread A")
    thread_b = await _thread(async_db, user_b.id, "Thread B")

    issue_a = await _issue(async_db, thread_a.id, "1")
    issue_b = await _issue(async_db, thread_b.id, "1")

    identity_a = await _identity(async_db, "comicvine", "100")
    identity_b = await _identity(async_db, "comicvine", "200")

    await _mapping(async_db, issue_a.id, identity_a.id, status="unresolved")
    await _mapping(async_db, issue_b.id, identity_b.id, status="candidate")

    items_a, total_a = await list_inbox_items(async_db, user_id=user_a.id)
    items_b, total_b = await list_inbox_items(async_db, user_id=user_b.id)

    assert total_a == 1
    assert len(items_a) == 1
    assert items_a[0].thread_title == "Thread A"
    assert items_a[0].provider == "comicvine"

    assert total_b == 1
    assert len(items_b) == 1
    assert items_b[0].thread_title == "Thread B"


@pytest.mark.asyncio
async def test_list_inbox_items_filters_by_status(async_db) -> None:
    """list_inbox_items only returns unresolved, candidate, and deferred mappings."""
    user = await _user(async_db)
    thread = await _thread(async_db, user.id, "Status Thread")
    issue = await _issue(async_db, thread.id, "1")
    identity = await _identity(async_db, "comicvine", "300")

    await _mapping(async_db, issue.id, identity.id, status="unresolved")
    await _mapping(async_db, issue.id, identity.id, status="candidate")
    await _mapping(async_db, issue.id, identity.id, status="deferred")
    await _mapping(async_db, issue.id, identity.id, status="confirmed")
    await _mapping(async_db, issue.id, identity.id, status="rejected")

    items, total = await list_inbox_items(async_db, user_id=user.id)

    assert total == 3
    assert len(items) == 3
    statuses = {item.status for item in items}
    assert statuses == {"unresolved", "candidate", "deferred"}


@pytest.mark.asyncio
async def test_list_inbox_items_pagination(async_db) -> None:
    """list_inbox_items respects offset and limit."""
    user = await _user(async_db)
    thread = await _thread(async_db, user.id, "Page Thread")
    issue = await _issue(async_db, thread.id, "1")
    identity = await _identity(async_db, "comicvine", "400")

    for _ in range(5):
        await _mapping(async_db, issue.id, identity.id, status="unresolved")

    first_page, total = await list_inbox_items(async_db, user_id=user.id, offset=0, limit=2)
    assert total == 5
    assert len(first_page) == 2

    second_page, _ = await list_inbox_items(async_db, user_id=user.id, offset=2, limit=2)
    assert len(second_page) == 2

    third_page, _ = await list_inbox_items(async_db, user_id=user.id, offset=4, limit=2)
    assert len(third_page) == 1


@pytest.mark.asyncio
async def test_list_inbox_items_ordered_by_created_at_desc(async_db) -> None:
    """list_inbox_items returns mappings ordered by created_at descending."""
    user = await _user(async_db)
    thread = await _thread(async_db, user.id, "Order Thread")
    issue = await _issue(async_db, thread.id, "1")
    identity = await _identity(async_db, "comicvine", "500")

    now = datetime.now(UTC)
    mappings: list[IssueExternalIdentityMapping] = []
    for i in range(3):
        mapping = IssueExternalIdentityMapping(
            issue_id=issue.id,
            external_identity_id=identity.id,
            status="unresolved",
            evidence_source="test",
            confidence=0.5,
            created_at=now + timedelta(seconds=i),
        )
        async_db.add(mapping)
        await async_db.flush()
        await async_db.refresh(mapping)
        mappings.append(mapping)

    items, _ = await list_inbox_items(async_db, user_id=user.id)
    assert len(items) == 3
    assert items[0].mapping_id == mappings[2].id  # newest first
    assert items[1].mapping_id == mappings[1].id
    assert items[2].mapping_id == mappings[0].id


@pytest.mark.asyncio
async def test_list_inbox_items_empty_for_user_without_mappings(async_db) -> None:
    """list_inbox_items returns empty list and zero total for a user with no mappings."""
    user = await _user(async_db)
    items, total = await list_inbox_items(async_db, user_id=user.id)
    assert items == []
    assert total == 0


@pytest.mark.asyncio
async def test_api_list_inbox_endpoint(async_db, client) -> None:
    """GET /api/v1/identity-inbox returns correct JSON through the API router."""
    user = await _user(async_db)
    thread = await _thread(async_db, user.id, "API Thread")
    issue = await _issue(async_db, thread.id, "1")
    identity = await _identity(async_db, "comicvine", "600")
    await _mapping(async_db, issue.id, identity.id, status="candidate")

    token = create_access_token(data={"sub": user.username, "jti": "test-api"})
    client.headers.update({"Authorization": f"Bearer {token}"})

    response = await client.get("/api/v1/identity-inbox?offset=0&limit=50")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["thread_title"] == "API Thread"
    assert item["issue_number"] == "1"
    assert item["status"] == "candidate"
    assert item["provider"] == "comicvine"
    assert item["source_entry_summary"] == "API Thread #1 (Test Volume) - Test Publisher"

