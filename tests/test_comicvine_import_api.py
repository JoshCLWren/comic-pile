"""Tests for the ComicVine identity-preserving import endpoint.

Covers exact identity preservation (thread + issue + confirmed external
identity mapping) and neighbor-anchored reading-order placement, including
the documented ambiguous-neighbor fallback rules.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread, User
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.reading_order import ReadingOrder, ReadingOrderItem


async def _make_thread(
    async_db: AsyncSession, *, user_id: int, title: str
) -> Thread:
    """Create and persist a minimal owned thread."""
    thread = Thread(
        user_id=user_id,
        title=title,
        format="Comic",
        issues_remaining=1,
        total_issues=1,
        queue_position=1,
    )
    async_db.add(thread)
    await async_db.flush()
    return thread


async def _make_order_with_items(
    async_db: AsyncSession,
    *,
    user_id: int,
    threads: list[Thread],
) -> ReadingOrder:
    """Create an owned reading order containing the given threads in order."""
    order = ReadingOrder(name="Arc Order", user_id=user_id)
    async_db.add(order)
    await async_db.flush()
    for position, thread in enumerate(threads, start=1):
        async_db.add(
            ReadingOrderItem(
                reading_order_id=order.id,
                thread_id=thread.id,
                position=position,
            )
        )
    await async_db.flush()
    return order


@pytest.mark.asyncio
async def test_import_preserves_exact_comicvine_identity(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Importing creates a thread whose issue carries the confirmed ComicVine id."""
    response = await auth_client.post(
        "/api/v1/comicvine/issues:import",
        json={
            "title": "Batman #125",
            "comicvine_issue_id": 12345,
            "issue_number": "125",
        },
    )

    assert response.status_code == 201
    body = response.json()

    thread = await async_db.get(Thread, body["thread_id"])
    assert thread is not None
    assert thread.user_id == default_user.id
    assert thread.title == "Batman #125"
    assert thread.format == "Comic"
    assert thread.total_issues == 1

    issue = await async_db.get(Issue, body["issue_id"])
    assert issue is not None
    assert issue.thread_id == thread.id
    assert issue.issue_number == "125"

    mapping_result = await async_db.execute(
        select(IssueExternalIdentityMapping).where(
            IssueExternalIdentityMapping.issue_id == issue.id
        )
    )
    mapping = mapping_result.scalar_one()

    assert mapping.status == "confirmed"
    identity = await async_db.get(ExternalIdentity, mapping.external_identity_id)
    assert identity is not None
    assert identity.provider == "comicvine"
    assert identity.entity_type == "issue"
    assert identity.external_id == "12345"
    assert body["reading_order_id"] is None
    assert body["position"] is None


@pytest.mark.asyncio
async def test_import_places_between_anchored_neighbors(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Both anchors present and ordered: insert strictly between them."""
    t1 = await _make_thread(async_db, user_id=default_user.id, title="Arc #1")
    t2 = await _make_thread(async_db, user_id=default_user.id, title="Arc #2")
    t3 = await _make_thread(async_db, user_id=default_user.id, title="Arc #3")
    order = await _make_order_with_items(async_db, user_id=default_user.id, threads=[t1, t2, t3])
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/comicvine/issues:import",
        json={
            "title": "Arc #1.5",
            "comicvine_issue_id": 20001,
            "issue_number": "1.5",
            "reading_order_id": order.id,
            "anchor_before_thread_id": t1.id,
            "anchor_after_thread_id": t2.id,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["reading_order_id"] == order.id
    assert body["position"] == 2
    assert body["total_items"] == 4

    result = await async_db.execute(
        select(ReadingOrderItem)
        .where(ReadingOrderItem.reading_order_id == order.id)
        .order_by(ReadingOrderItem.position)
    )
    positions = {item.thread_id: item.position for item in result.scalars().all()}
    new_thread_id = body["thread_id"]
    assert positions[t1.id] == 1
    assert positions[new_thread_id] == 2
    assert positions[t2.id] == 3
    assert positions[t3.id] == 4


@pytest.mark.asyncio
async def test_import_only_before_anchor_places_after_it(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Only the preceding arc member is in the order: insert directly after it."""
    t1 = await _make_thread(async_db, user_id=default_user.id, title="Arc #1")
    other = await _make_thread(async_db, user_id=default_user.id, title="Unrelated")
    order = await _make_order_with_items(async_db, user_id=default_user.id, threads=[t1, other])
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/comicvine/issues:import",
        json={
            "title": "Arc #2",
            "comicvine_issue_id": 20002,
            "reading_order_id": order.id,
            "anchor_before_thread_id": t1.id,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["position"] == 2

    result = await async_db.execute(
        select(ReadingOrderItem)
        .where(ReadingOrderItem.reading_order_id == order.id)
        .order_by(ReadingOrderItem.position)
    )
    positions = {item.thread_id: item.position for item in result.scalars().all()}
    assert positions[body["thread_id"]] == 2
    assert positions[other.id] == 3


@pytest.mark.asyncio
async def test_import_only_after_anchor_places_before_it(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Only the following arc member is in the order: insert directly before it."""
    other = await _make_thread(async_db, user_id=default_user.id, title="Unrelated")
    t2 = await _make_thread(async_db, user_id=default_user.id, title="Arc #2")
    order = await _make_order_with_items(async_db, user_id=default_user.id, threads=[other, t2])
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/comicvine/issues:import",
        json={
            "title": "Arc #1",
            "comicvine_issue_id": 20003,
            "reading_order_id": order.id,
            "anchor_after_thread_id": t2.id,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["position"] == 2

    result = await async_db.execute(
        select(ReadingOrderItem)
        .where(ReadingOrderItem.reading_order_id == order.id)
        .order_by(ReadingOrderItem.position)
    )
    positions = {item.thread_id: item.position for item in result.scalars().all()}
    assert positions[other.id] == 1
    assert positions[body["thread_id"]] == 2
    assert positions[t2.id] == 3


@pytest.mark.asyncio
async def test_import_unknown_anchor_appends(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Anchors absent from the target order fall back to appending at the end."""
    t1 = await _make_thread(async_db, user_id=default_user.id, title="Present")
    order = await _make_order_with_items(async_db, user_id=default_user.id, threads=[t1])
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/comicvine/issues:import",
        json={
            "title": "Arc #9",
            "comicvine_issue_id": 20004,
            "reading_order_id": order.id,
            "anchor_before_thread_id": 999999,
            "anchor_after_thread_id": 888888,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["position"] == 2
    assert body["total_items"] == 2


@pytest.mark.asyncio
async def test_import_conflicting_anchors_keep_preceding_adjacency(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Contradictory anchor ordering resolves adjacent to the preceding member."""
    early = await _make_thread(async_db, user_id=default_user.id, title="Early")
    late = await _make_thread(async_db, user_id=default_user.id, title="Late")
    order = await _make_order_with_items(async_db, user_id=default_user.id, threads=[early, late])
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/comicvine/issues:import",
        json={
            "title": "Arc #X",
            "comicvine_issue_id": 20005,
            "reading_order_id": order.id,
            "anchor_before_thread_id": late.id,
            "anchor_after_thread_id": early.id,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["position"] == 3

    result = await async_db.execute(
        select(ReadingOrderItem)
        .where(ReadingOrderItem.reading_order_id == order.id)
        .order_by(ReadingOrderItem.position)
    )
    positions = {item.thread_id: item.position for item in result.scalars().all()}
    assert positions[early.id] == 1
    assert positions[late.id] == 2
    assert positions[body["thread_id"]] == 3


@pytest.mark.asyncio
async def test_import_without_order_skips_placement(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """No reading order requested means no placement is attempted."""
    response = await auth_client.post(
        "/api/v1/comicvine/issues:import",
        json={"title": "Loose Issue", "comicvine_issue_id": 20006},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["reading_order_id"] is None
    assert body["position"] is None
    assert body["total_items"] is None

    thread = await async_db.get(Thread, body["thread_id"])
    assert thread is not None


@pytest.mark.asyncio
async def test_import_unknown_reading_order_returns_404(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A nonexistent reading order fails the import without creating anything."""
    threads_before = (
        (await async_db.execute(select(Thread))).scalars().all()
    )

    response = await auth_client.post(
        "/api/v1/comicvine/issues:import",
        json={
            "title": "Never Created",
            "comicvine_issue_id": 20007,
            "reading_order_id": 999999,
        },
    )

    assert response.status_code == 404
    threads_after = (
        (await async_db.execute(select(Thread))).scalars().all()
    )
    assert len(threads_after) == len(threads_before)


@pytest.mark.asyncio
async def test_import_requires_authentication(async_db: AsyncSession) -> None:
    """Unauthenticated import requests are rejected."""
    from httpx import ASGITransport

    from app.main import app as fastapi_app

    transport = ASGITransport(app=fastapi_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/comicvine/issues:import",
            json={"title": "Anon", "comicvine_issue_id": 1},
        )
    assert response.status_code in (401, 403)
