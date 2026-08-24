"""Regression coverage for Snooze-as-session-correction queue behavior.

Snooze is a temporary session correction, not a durable dislike
(issue #1727): snoozing excludes a thread from rolls for the active
session and widens the die, but it must never mutate the thread's
durable ``queue_position``. Long-term ordering stays governed by ratings
and explicit queue actions.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread
from app.models import Session as SessionModel
from comic_pile.queue import get_roll_pool


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


async def _snooze_pending_thread(auth_client: AsyncClient) -> dict:
    """POST the snooze endpoint and return the validated JSON payload."""
    response = await auth_client.post("/api/snooze/")
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_snooze_keeps_durable_queue_position(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Snoozing widens the die and excludes the thread without reordering the queue."""
    user_id, threads = await _create_pending_snooze_session(async_db, thread_count=10)
    target = threads[0]
    queue_before = await _load_queue(async_db, user_id)

    data = await _snooze_pending_thread(auth_client)

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

    data = await _snooze_pending_thread(auth_client)

    assert data["current_die"] == 8
    assert set(data["snoozed_thread_ids"]) == {target.id, already_snoozed.id}

    assert await _load_queue(async_db, user_id) == queue_before


@pytest.mark.asyncio
async def test_snoozed_thread_returns_at_durable_position_in_later_session(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A snoozed thread rejoins the roll pool at its original position once its session ends."""
    user_id, threads = await _create_pending_snooze_session(async_db, thread_count=10)
    target = threads[0]

    data = await _snooze_pending_thread(auth_client)
    assert target.id in data["snoozed_thread_ids"]

    # Expire the active session and start a fresh one so session-scoped
    # snooze state cannot leak into the later session's roll pool.
    result = await async_db.execute(
        select(SessionModel).where(
            SessionModel.user_id == user_id,
            SessionModel.ended_at.is_(None),
        )
    )
    for active_session in result.scalars().all():
        active_session.ended_at = active_session.started_at
    async_db.add(SessionModel(start_die=6, user_id=user_id))
    await async_db.commit()

    # Exclusion is driven purely by the session's snooze list: supplying it
    # removes the target from the pool.
    pool_with_old_snoozes = await get_roll_pool(
        user_id, async_db, snoozed_ids=list(data["snoozed_thread_ids"])
    )
    assert target.id not in [thread.id for thread in pool_with_old_snoozes]

    # A later session starts with no snoozes, so the target returns at its
    # durable position.
    later_session_pool = await get_roll_pool(user_id, async_db)
    assert [thread.id for thread in later_session_pool][0] == target.id
    assert later_session_pool[0].queue_position == 1
