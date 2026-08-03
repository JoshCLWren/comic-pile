"""Regression coverage for snooze queue placement."""

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


async def _load_queue(async_db: AsyncSession, user_id: int):
    """Return the user's queue in deterministic position order."""
    result = await async_db.execute(
        select(Thread.id, Thread.queue_position)
        .where(Thread.user_id == user_id)
        .order_by(Thread.queue_position, Thread.id)
    )
    return result.all()


@pytest.mark.asyncio
async def test_snooze_moves_thread_beyond_widened_roll_range(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Snoozing uses the same safe-position behavior as a low rating."""
    user_id, threads = await _create_pending_snooze_session(async_db, thread_count=10)
    target = threads[0]

    response = await auth_client.post("/api/snooze/")

    assert response.status_code == 200
    assert response.json()["current_die"] == 8

    queue = await _load_queue(async_db, user_id)

    assert queue[8].id == target.id
    assert queue[8].queue_position == 9
    assert [row.queue_position for row in queue] == list(range(1, 11))


@pytest.mark.asyncio
async def test_snooze_placement_does_not_count_existing_snoozed_threads(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Already-snoozed threads do not consume slots in the widened roll pool."""
    user_id, threads = await _create_pending_snooze_session(
        async_db,
        thread_count=11,
        snoozed_indexes=[1],
    )
    target = threads[0]
    already_snoozed = threads[1]

    response = await auth_client.post("/api/snooze/")

    assert response.status_code == 200
    assert response.json()["current_die"] == 8
    assert set(response.json()["snoozed_thread_ids"]) == {target.id, already_snoozed.id}

    queue = await _load_queue(async_db, user_id)

    assert queue[9].id == target.id
    assert queue[9].queue_position == 10
    assert [row.queue_position for row in queue] == list(range(1, 12))
