"""E2E integration tests for dice ladder behavior through API."""

import pytest

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as SQLAlchemyAsyncSession

from app.models import Event, Thread, User
from app.models import Session as SessionModel


@pytest.mark.asyncio
async def test_dice_ladder_rating_goes_down(
    auth_api_client_async: AsyncClient,
    async_db: SQLAlchemyAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rating 4+ causes session die to go DOWN (d10 → d8)."""
    monkeypatch.setattr("random.randint", lambda _a, _b: 0)

    result = await async_db.execute(select(User).where(User.username == "test_user@example.com"))
    user = result.scalar_one_or_none()
    if not user:
        user = User(username="test_user@example.com")
        async_db.add(user)
        await async_db.commit()
        await async_db.refresh(user)

    thread = Thread(
        title="Green Lantern",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    roll_response = await auth_api_client_async.post("/api/roll/")
    assert roll_response.status_code == 200
    roll_data = roll_response.json()

    assert roll_data["die_size"] == 10

    rate_response = await auth_api_client_async.post(
        "/api/rate/", json={"rating": 4.0, "issues_read": 1}
    )
    assert rate_response.status_code == 200

    result = await async_db.execute(
        select(Event)
        .where(Event.session_id == session.id)
        .where(Event.type == "rate")
        .order_by(Event.timestamp.desc())
    )
    rate_events = result.scalars().all()
    assert len(rate_events) == 1
    assert rate_events[0].die_after == 8


@pytest.mark.asyncio
async def test_dice_ladder_rating_goes_up(
    auth_api_client_async: AsyncClient,
    async_db: SQLAlchemyAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rating below 4 causes session die to go UP (d10 → d12)."""
    monkeypatch.setattr("random.randint", lambda _a, _b: 0)

    result = await async_db.execute(select(User).where(User.username == "test_user@example.com"))
    user = result.scalar_one_or_none()
    if not user:
        user = User(username="test_user@example.com")
        async_db.add(user)
        await async_db.commit()
        await async_db.refresh(user)

    thread = Thread(
        title="Shazam",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    roll_response = await auth_api_client_async.post("/api/roll/")
    assert roll_response.status_code == 200
    roll_data = roll_response.json()

    assert roll_data["die_size"] == 10

    rate_response = await auth_api_client_async.post(
        "/api/rate/", json={"rating": 3.0, "issues_read": 1}
    )
    assert rate_response.status_code == 200

    result = await async_db.execute(
        select(Event)
        .where(Event.session_id == session.id)
        .where(Event.type == "rate")
        .order_by(Event.timestamp.desc())
    )
    rate_events = result.scalars().all()
    assert len(rate_events) == 1
    assert rate_events[0].die_after == 12


@pytest.mark.asyncio
async def test_dice_ladder_snooze_goes_up(
    auth_api_client_async: AsyncClient,
    async_db: SQLAlchemyAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Snoozing causes session die to go UP (d6 → d8)."""
    monkeypatch.setattr("random.randint", lambda _a, _b: 0)

    result = await async_db.execute(select(User).where(User.username == "test_user@example.com"))
    user = result.scalar_one_or_none()
    if not user:
        user = User(username="test_user@example.com")
        async_db.add(user)
        await async_db.commit()
        await async_db.refresh(user)

    thread = Thread(
        title="Batman Beyond",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    session = SessionModel(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    roll_response = await auth_api_client_async.post("/api/roll/")
    assert roll_response.status_code == 200

    roll_data = roll_response.json()
    assert roll_data["die_size"] == 6

    snooze_response = await auth_api_client_async.post("/api/snooze/")
    assert snooze_response.status_code == 200
    snooze_data = snooze_response.json()

    assert snooze_data["manual_die"] == 8

    result = await async_db.execute(
        select(Event)
        .where(Event.session_id == session.id)
        .where(Event.type == "snooze")
        .order_by(Event.timestamp.desc())
    )
    snooze_events = result.scalars().all()
    assert len(snooze_events) == 1
    assert snooze_events[0].die_after == 8


@pytest.mark.asyncio
async def test_finish_session_clears_snoozed(
    auth_api_client_async: AsyncClient,
    async_db: SQLAlchemyAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that finishing a session clears snoozed_thread_ids."""
    monkeypatch.setattr("random.randint", lambda _a, _b: 0)

    result = await async_db.execute(select(User).where(User.username == "test_user@example.com"))
    user = result.scalar_one_or_none()
    if not user:
        user = User(username="test_user@example.com")
        async_db.add(user)
        await async_db.commit()
        await async_db.refresh(user)

    thread1 = Thread(
        title="Superman",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    thread2 = Thread(
        title="Wonder Woman",
        format="Comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread1)
    async_db.add(thread2)
    await async_db.commit()
    await async_db.refresh(thread1)
    await async_db.refresh(thread2)

    session = SessionModel(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    await auth_api_client_async.post("/api/roll/")
    snooze_response = await auth_api_client_async.post("/api/snooze/")
    assert snooze_response.status_code == 200
    snooze_data = snooze_response.json()
    assert len(snooze_data["snoozed_thread_ids"]) == 1

    await auth_api_client_async.post("/api/roll/")

    await async_db.refresh(thread2)
    rate_response = await auth_api_client_async.post(
        "/api/rate/",
        json={"rating": 4.0, "issues_read": thread2.issues_remaining, "finish_session": True},
    )
    assert rate_response.status_code == 200

    await async_db.refresh(session)
    assert session.ended_at is not None

    snoozed_count = len(session.snoozed_thread_ids) if session.snoozed_thread_ids else 0
    assert snoozed_count == 0
