"""API workflow integration tests."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import Event, Thread, User
from app.models import Session as SessionModel


@pytest.mark.asyncio
@pytest.mark.integration
async def test_roll_dice_updates_session(
    auth_api_client_async: AsyncClient, async_db: AsyncSession
):
    """Post to /roll, verify session updated in database."""
    result = await async_db.execute(select(User).where(User.username == "test_user@example.com"))
    user = result.scalar_one()
    thread = Thread(
        title="Test Comic", format="Comic", issues_remaining=5, queue_position=1, user_id=user.id
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_api_client_async.post("/api/roll/")
    assert response.status_code == 200

    session_result = await async_db.execute(
        select(SessionModel).where(SessionModel.ended_at.is_(None))
    )
    session = session_result.scalar_one_or_none()
    assert session is not None
    assert session.start_die == 6


@pytest.mark.asyncio
@pytest.mark.integration
async def test_rate_comic_updates_rating(auth_api_client: AsyncClient, db: Session):
    """Post to /rate, verify thread rating updated."""
    user = db.execute(select(User).where(User.username == "test_user@example.com")).scalar_one()
    thread = Thread(
        title="Test Comic", format="Comic", issues_remaining=5, queue_position=1, user_id=user.id
    )
    db.add(thread)
    db.commit()

    session = SessionModel(start_die=6, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    roll_event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=1,
        selection_method="random",
    )
    db.add(roll_event)
    db.commit()

    response = await auth_api_client.post(
        "/api/rate/", json={"thread_id": thread.id, "rating": 4.0, "issues_read": 1}
    )
    assert response.status_code == 200

    db.refresh(thread)
    assert thread.last_rating == 4.0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_add_to_queue_updates_queue(auth_api_client: AsyncClient, db: Session):
    """POST to /threads/, verify queue order changed."""
    user = db.execute(select(User).where(User.username == "test_user@example.com")).scalar_one()
    thread1 = Thread(
        title="Comic 1", format="Comic", issues_remaining=5, queue_position=1, user_id=user.id
    )
    thread2 = Thread(
        title="Comic 2", format="Comic", issues_remaining=3, queue_position=2, user_id=user.id
    )
    db.add(thread1)
    db.add(thread2)
    db.commit()

    response = await auth_api_client.post(
        "/api/threads/", json={"title": "Comic 3", "format": "Comic", "issues_remaining": 4}
    )
    assert response.status_code == 201

    new_thread = db.execute(select(Thread).where(Thread.title == "Comic 3")).scalar_one()
    assert new_thread.queue_position == 3


@pytest.mark.asyncio
@pytest.mark.integration
async def test_session_persists_across_requests(auth_api_client: AsyncClient, db: Session):
    """Make multiple requests with same session, verify session ID stays consistent."""
    user = db.execute(select(User).where(User.username == "test_user@example.com")).scalar_one()
    thread = Thread(
        title="Test Comic", format="Comic", issues_remaining=5, queue_position=1, user_id=user.id
    )
    db.add(thread)
    db.commit()

    await auth_api_client.post("/api/roll/")

    session1 = db.execute(select(SessionModel).where(SessionModel.ended_at.is_(None))).scalar_one()
    session_id = session1.id

    await auth_api_client.post("/api/roll/")

    session2 = db.execute(select(SessionModel).where(SessionModel.ended_at.is_(None))).scalar_one()
    assert session2.id == session_id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_complete_task_advances_queue(auth_api_client: AsyncClient, db: Session):
    """Mark session complete, verify queue advances."""
    user = db.execute(select(User).where(User.username == "test_user@example.com")).scalar_one()
    thread = Thread(
        title="Test Comic", format="Comic", issues_remaining=1, queue_position=1, user_id=user.id
    )
    db.add(thread)
    db.commit()

    session = SessionModel(start_die=6, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    roll_event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=1,
        selection_method="random",
    )
    db.add(roll_event)
    db.commit()

    response = await auth_api_client.post(
        "/api/rate/",
        json={"thread_id": thread.id, "rating": 4.0, "issues_read": 1, "finish_session": True},
    )
    assert response.status_code == 200

    db.refresh(thread)
    assert thread.status == "completed"
    assert session.ended_at is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_csv_export_returns_valid_csv(
    auth_api_client: AsyncClient, db: Session, enable_internal_ops
):
    """GET /export/csv, verify Content-Type and structure."""
    user = db.execute(select(User).where(User.username == "test_user@example.com")).scalar_one()
    thread = Thread(
        title="Test Comic", format="Comic", issues_remaining=5, queue_position=1, user_id=user.id
    )
    db.add(thread)
    db.commit()

    response = await auth_api_client.get("/api/admin/export/csv/")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"

    content = response.text
    assert "title,format,issues_remaining" in content
    assert "Test Comic" in content
