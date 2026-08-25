"""Regression test for SQLAlchemy greenlet error when accessing user after commit."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import Event, Snapshot, Thread
from app.models import Session as SessionModel
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_rate_creates_snapshot_without_greenlet_error(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Regression test for accessing current_user.id after db.commit().

    Previously failed with: sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called
    when snapshot_thread_states tried to use current_user.id after the endpoint's commit.

    Fixed by capturing user_id before commit instead of accessing current_user.id after.
    """
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    response = await auth_client.post("/api/v1/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 200

    result = await async_db.execute(
        select(Event).where(Event.session_id == session.id).where(Event.type == "rate")
    )
    rate_event = result.scalars().first()
    assert rate_event is not None

    result = await async_db.execute(select(Snapshot).where(Snapshot.session_id == session.id))
    snapshot = result.scalars().first()
    assert snapshot is not None, "Snapshot should be created without greenlet error"
