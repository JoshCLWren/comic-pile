"""Regression coverage for snooze queue placement.

Snooze is a temporary session correction, not a durable dislike
(issue #1721): snoozing excludes a thread from rolls for the active
session and widens the die, but it must never mutate the thread's
durable ``queue_position``. Long-term ordering stays governed by
ratings and explicit queue actions.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread
from app.models import Session as SessionModel


async def _create_pending_snooze_session(
    async_db: AsyncSession,
    *,
    thread_count: int,
    snoozed_indexes: list[int] | None = None,
) -> tuple[int, list[Thread]]:
    """Create a session whose first thread is pending for snooze."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    threads = [
        Thread(
            title=f"Thread {index}",
            format="Comic",
            issues_remaining=5,
            queue_position=index,
            status="active",
            user_id=user.id,
        )
        for index in range(1, thread_count + 1)
    ]
    async_db.add_all(threads)
    await async_db.flush()

    snoozed_ids = [threads[index].id for index in snoozed_indexes or []]
    target = threads[0]
    session = SessionModel(
        start_die=6,
        user_id=user.id,
        pending_thread_id=target.id,
        snoozed_thread_ids=snoozed_ids,
    )
    async_db.add(session)
    await async_db.flush()
    async_db.add(
        Event(
            type="roll",
            die=6,
            result=1,
            selected_thread_id=target.id,
            selection_method="random",
            session_id=session.id,
            thread_id=target.id,
        )
    )
    await async_db.commit()
    return user.id, threads


async def _load_queue(async_db: AsyncSession, user_id: int) -> list[tuple[int, int]]:
    """Return the user's queue in deterministic position order."""
    result = await async_db.execute(
        select(Thread.id, Thread.queue_position)
        .where(Thread.user_id == user_id)
        .order_by(Thread.queue_position, Thread.id)
    )
    return [(row.id, row.queue_position) for row in result.all()]


@pytest.mark.asyncio
async def test_snooze_keeps_durable_queue_position(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Snoozing widens the die and excludes the thread without reordering the queue."""
    user_id, threads = await _create_pending_snooze_session(async_db, thread_count=10)
    target = threads[0]
    queue_before = await _load_queue(async_db, user_id)

    response = await auth_client.post("/api/snooze/")

    assert response.status_code == 200
    data = response.json()
    assert data["current_die"] == 8
    assert target.id in data["snoozed_thread_ids"]

    queue_after = await _load_queue(async_db, user_id)

    assert queue_after == queue_before
    assert dict(queue_after)[target.id] == 1


@pytest.mark.asyncio
async def test_snooze_leaves_queue_untouched_with_existing_snoozed_threads(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Pre-existing snoozed state does not trigger any durable queue mutation."""
    user_id, threads = await _create_pending_snooze_session(
        async_db,
        thread_count=11,
        snoozed_indexes=[1],
    )
    target = threads[0]
    already_snoozed = threads[1]
    queue_before = await _load_queue(async_db, user_id)

    response = await auth_client.post("/api/snooze/")

    assert response.status_code == 200
    data = response.json()
    assert data["current_die"] == 8
    assert set(data["snoozed_thread_ids"]) == {target.id, already_snoozed.id}

    queue_after = await _load_queue(async_db, user_id)

    assert queue_after == queue_before


@pytest.mark.asyncio
async def test_high_affinity_thread_returns_with_position_after_session_expiry(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A highly rated snoozed thread rejoins the next session at its durable position."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    target = Thread(
        title="High Affinity Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        last_rating=5.0,
    )
    other = Thread(
        title="Other Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    async_db.add_all([target, other])
    await async_db.flush()

    session = SessionModel(
        start_die=6,
        user_id=user.id,
        pending_thread_id=target.id,
    )
    async_db.add(session)
    await async_db.flush()
    async_db.add(
        Event(
            type="roll",
            die=6,
            result=1,
            selected_thread_id=target.id,
            selection_method="random",
            session_id=session.id,
            thread_id=target.id,
        )
    )
    await async_db.commit()

    snooze_response = await auth_client.post("/api/snooze/")
    assert snooze_response.status_code == 200
    assert target.id in snooze_response.json()["snoozed_thread_ids"]

    # The snoozed thread is excluded for the rest of the active session:
    # overriding it explicitly is rejected while the snooze state lives.
    override_while_snoozed = await auth_client.post(
        "/api/roll/override", json={"thread_id": target.id}
    )
    assert override_while_snoozed.status_code == 400
    assert "is snoozed" in override_while_snoozed.json()["detail"]

    # Session snooze state expires with the session itself.
    session_result = await async_db.execute(
        select(SessionModel).where(SessionModel.user_id == user.id)
    )
    expired_session = session_result.scalars().one()
    expired_session.ended_at = datetime.now(UTC)
    await async_db.commit()

    # A fresh session has no snoozed threads, so the same thread is selectable
    # again and reports its untouched durable queue position.
    override_after_expiry = await auth_client.post(
        "/api/roll/override", json={"thread_id": target.id}
    )
    assert override_after_expiry.status_code == 200
    override_data = override_after_expiry.json()
    assert override_data["thread_id"] == target.id
    assert override_data["queue_position"] == 1
    assert override_data["snoozed_count"] == 0

    refreshed_target = await async_db.get(Thread, target.id)
    assert refreshed_target is not None
    assert refreshed_target.queue_position == 1


@pytest.mark.asyncio
async def test_rating_still_moves_queue_while_snooze_does_not(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Snooze never reorders the queue; a low rating in the same session still does."""
    user_id, threads = await _create_pending_snooze_session(async_db, thread_count=3)
    snoozed_thread = threads[0]

    snooze_response = await auth_client.post("/api/snooze/")
    assert snooze_response.status_code == 200
    assert await _load_queue(async_db, user_id) == [
        (threads[0].id, 1),
        (threads[1].id, 2),
        (threads[2].id, 3),
    ]

    # Deterministically make one of the unsnoozed threads pending. A random
    # roll would pick between the two remaining candidates.
    override_response = await auth_client.post(
        "/api/roll/override", json={"thread_id": threads[1].id}
    )
    assert override_response.status_code == 200
    rolled_thread_id = threads[1].id

    rate_response = await auth_client.post(
        "/api/rate/",
        json={"rating": 2.0, "issues_read": 1, "finish_session": False},
    )
    assert rate_response.status_code == 200

    queue_after_rating = await _load_queue(async_db, user_id)

    # The snoozed thread kept its durable slot; the low-rated thread was demoted.
    assert dict(queue_after_rating)[snoozed_thread.id] == 1
    assert dict(queue_after_rating)[rolled_thread_id] == 3
