"""Regression coverage for snooze queue placement."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread
from app.models import Session as SessionModel


@pytest.mark.asyncio
async def test_snooze_moves_thread_beyond_widened_roll_range(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Snoozing uses the same safe-position behavior as a low rating."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    session = SessionModel(start_die=6, user_id=user.id)
    async_db.add(session)

    threads = [
        Thread(
            title=f"Thread {index}",
            format="Comic",
            issues_remaining=5,
            queue_position=index,
            status="active",
            user_id=user.id,
        )
        for index in range(1, 11)
    ]
    async_db.add_all(threads)
    await async_db.commit()
    await async_db.refresh(session)
    for thread in threads:
        await async_db.refresh(thread)

    target = threads[0]
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
    session.pending_thread_id = target.id
    await async_db.commit()

    response = await auth_client.post("/api/snooze/")

    assert response.status_code == 200
    assert response.json()["current_die"] == 8

    result = await async_db.execute(
        select(Thread.id, Thread.queue_position)
        .where(Thread.user_id == user.id)
        .order_by(Thread.queue_position, Thread.id)
    )
    queue = result.all()

    assert queue[8].id == target.id
    assert queue[8].queue_position == 9
    assert [row.queue_position for row in queue] == list(range(1, 11))
