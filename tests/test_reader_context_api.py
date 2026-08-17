"""Tests for the reader-context API endpoint."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DependencyGroup,
    DependencyGroupMembership,
    Event,
    ExternalIdentity,
    Issue,
    Thread,
    ThreadExternalSeriesMapping,
)
from tests.conftest import get_or_create_user_async


@pytest.mark.asyncio
async def test_reader_context_no_canonical_identity(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Returns unavailable state when no canonical series identity exists."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Spider-Man",
        format="Comic",
        issues_remaining=3,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    issue = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    async_db.add(issue)
    await async_db.flush()

    response = await auth_client.get(f"/api/v1/issues/{issue.id}/reader-context")
    assert response.status_code == 200
    data = response.json()
    assert data["canonical_series"]["identity_source"] == "unavailable"
    assert data["canonical_series"]["average_rating"] is None
    assert data["canonical_series"]["rated_count"] == 0
    assert data["crossover_panel"] == []


@pytest.mark.asyncio
async def test_reader_context_with_canonical_identity(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Returns series analytics when a confirmed canonical identity exists."""
    user = await get_or_create_user_async(async_db)

    thread1 = Thread(
        title="Thanos (2003)",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    thread2 = Thread(
        title="Thanos (2004)",
        format="Comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add_all([thread1, thread2])
    await async_db.flush()

    issue1 = Issue(
        thread_id=thread1.id,
        issue_number="1",
        position=1,
        status="read",
        read_at=datetime.now(UTC),
    )
    issue2 = Issue(
        thread_id=thread1.id,
        issue_number="2",
        position=2,
        status="unread",
    )
    issue3 = Issue(
        thread_id=thread2.id,
        issue_number="1",
        position=1,
        status="read",
        read_at=datetime.now(UTC),
    )
    async_db.add_all([issue1, issue2, issue3])
    await async_db.flush()

    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="series-12345",
        metadata_json={"name": "Thanos"},
    )
    async_db.add(identity)
    await async_db.flush()

    mapping1 = ThreadExternalSeriesMapping(
        thread_id=thread1.id,
        external_identity_id=identity.id,
        status="confirmed",
    )
    mapping2 = ThreadExternalSeriesMapping(
        thread_id=thread2.id,
        external_identity_id=identity.id,
        status="confirmed",
    )
    async_db.add_all([mapping1, mapping2])
    await async_db.flush()

    event1 = Event(
        type="rate",
        rating=4.5,
        thread_id=thread1.id,
        timestamp=datetime.now(UTC),
    )
    event2 = Event(
        type="rate",
        rating=3.0,
        thread_id=thread2.id,
        timestamp=datetime.now(UTC),
    )
    async_db.add_all([event1, event2])
    await async_db.flush()

    response = await auth_client.get(f"/api/v1/issues/{issue2.id}/reader-context")
    assert response.status_code == 200
    data = response.json()

    cs = data["canonical_series"]
    assert cs["identity_source"] == "external_identity"
    assert cs["rated_count"] == 2
    assert cs["average_rating"] is not None
    assert cs["highest_rating"] == 4.5
    assert cs["lowest_rating"] == 3.0
    assert cs["previous_issue"] is not None
    assert cs["previous_issue"]["issue_number"] == "1"
    assert cs["previous_issue"]["is_read"] is True
    assert len(cs["recent_ratings"]) == 2


@pytest.mark.asyncio
async def test_reader_context_crossover_panel(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Returns crossover analytics for applicable dependency groups."""
    user = await get_or_create_user_async(async_db)

    thread1 = Thread(
        title="Avengers",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    thread2 = Thread(
        title="X-Men",
        format="Comic",
        issues_remaining=0,
        queue_position=2,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add_all([thread1, thread2])
    await async_db.flush()

    issue1 = Issue(
        thread_id=thread1.id,
        issue_number="1",
        position=1,
        status="read",
        read_at=datetime.now(UTC),
    )
    issue2 = Issue(
        thread_id=thread2.id,
        issue_number="1",
        position=1,
        status="read",
        read_at=datetime.now(UTC),
    )
    async_db.add_all([issue1, issue2])
    await async_db.flush()

    group = DependencyGroup(
        user_id=user.id,
        name="Avengers vs X-Men",
    )
    async_db.add(group)
    await async_db.flush()

    membership1 = DependencyGroupMembership(
        group_id=group.id,
        thread_id=thread1.id,
    )
    membership2 = DependencyGroupMembership(
        group_id=group.id,
        thread_id=thread2.id,
    )
    async_db.add_all([membership1, membership2])
    await async_db.flush()

    event1 = Event(type="rate", rating=4.0, thread_id=thread1.id, timestamp=datetime.now(UTC))
    event2 = Event(type="rate", rating=3.5, thread_id=thread2.id, timestamp=datetime.now(UTC))
    async_db.add_all([event1, event2])
    await async_db.flush()

    response = await auth_client.get(f"/api/v1/issues/{issue1.id}/reader-context")
    assert response.status_code == 200
    data = response.json()

    assert len(data["crossover_panel"]) == 1
    panel = data["crossover_panel"][0]
    assert panel["group_name"] == "Avengers vs X-Men"
    assert panel["rated_count"] == 2
    assert panel["read_count"] == 2
    assert panel["node_count"] == 2
    assert len(panel["nodes"]) == 2


@pytest.mark.asyncio
async def test_reader_context_404_not_found(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Returns 404 for non-existent issue."""
    response = await auth_client.get("/api/v1/issues/99999/reader-context")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_reader_context_404_not_owned(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Returns 404 for issue owned by a different user."""
    user = await get_or_create_user_async(async_db)

    other_user_thread = Thread(
        title="Other User Thread",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=9999,
        created_at=datetime.now(UTC),
    )
    async_db.add(other_user_thread)
    await async_db.flush()

    other_issue = Issue(
        thread_id=other_user_thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    async_db.add(other_issue)
    await async_db.flush()

    response = await auth_client.get(f"/api/v1/issues/{other_issue.id}/reader-context")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_reader_context_empty_series(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Returns zero counts when canonical identity exists but no ratings."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="New Series",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    issue = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    async_db.add(issue)
    await async_db.flush()

    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="series-empty",
        metadata_json={"name": "New Series"},
    )
    async_db.add(identity)
    await async_db.flush()

    mapping = ThreadExternalSeriesMapping(
        thread_id=thread.id,
        external_identity_id=identity.id,
        status="confirmed",
    )
    async_db.add(mapping)
    await async_db.flush()

    response = await auth_client.get(f"/api/v1/issues/{issue.id}/reader-context")
    assert response.status_code == 200
    data = response.json()

    cs = data["canonical_series"]
    assert cs["identity_source"] == "external_identity"
    assert cs["rated_count"] == 0
    assert cs["average_rating"] is None
    assert cs["highest_rating"] is None
    assert cs["lowest_rating"] is None
    assert cs["recent_ratings"] == []
    assert cs["previous_issue"] is None
