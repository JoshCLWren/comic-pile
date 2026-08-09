"""Regression coverage for auth-expired Roll mutation replay safety."""

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token
from app.models import Event, Thread
from app.models import Session as SessionModel
from tests.conftest import get_or_create_user_async


async def _pending_roll(async_db: AsyncSession, *, start_die: int = 6) -> tuple[SessionModel, Thread]:
    """Create one active session with one pending rolled thread."""
    user = await get_or_create_user_async(async_db)
    session = SessionModel(start_die=start_die, user_id=user.id)
    thread = Thread(
        title="Auth replay thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add_all([session, thread])
    await async_db.flush()
    session.pending_thread_id = thread.id
    async_db.add(
        Event(
            type="roll",
            die=start_die,
            result=1,
            selected_thread_id=thread.id,
            selection_method="random",
            session_id=session.id,
            thread_id=thread.id,
        )
    )
    await async_db.commit()
    return session, thread


def _set_access_token(client: AsyncClient, username: str, *, expired: bool) -> None:
    """Replace the client's access token with a deterministic valid or expired token."""
    lifetime = timedelta(minutes=-1 if expired else 5)
    token = create_access_token(
        data={"sub": username, "jti": "expired-replay" if expired else "fresh-replay"},
        expires_delta=lifetime,
    )
    client.headers.update({"Authorization": f"Bearer {token}"})


@pytest.mark.asyncio
async def test_rate_expired_token_has_no_partial_write_and_replay_commits_once(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    test_username: str,
) -> None:
    """A rejected rate can be replayed after auth recovery without a duplicate transition."""
    session, thread = await _pending_roll(async_db)

    _set_access_token(auth_client, test_username, expired=True)
    rejected = await auth_client.post("/api/rate/", json={"rating": 4.5})
    assert rejected.status_code == 401

    await async_db.refresh(session)
    await async_db.refresh(thread)
    assert session.pending_thread_id == thread.id
    assert thread.issues_remaining == 5
    assert thread.last_rating is None
    result = await async_db.execute(
        select(Event).where(Event.session_id == session.id, Event.type == "rate")
    )
    assert result.scalars().all() == []

    _set_access_token(auth_client, test_username, expired=False)
    replay = await auth_client.post("/api/rate/", json={"rating": 4.5})
    assert replay.status_code == 200

    duplicate = await auth_client.post("/api/rate/", json={"rating": 4.5})
    assert duplicate.status_code == 400

    await async_db.refresh(session)
    await async_db.refresh(thread)
    assert session.pending_thread_id is None
    assert thread.issues_remaining == 4
    assert thread.last_rating == 4.5
    result = await async_db.execute(
        select(Event).where(Event.session_id == session.id, Event.type == "rate")
    )
    rate_events = result.scalars().all()
    assert len(rate_events) == 1
    assert rate_events[0].thread_id == thread.id


@pytest.mark.asyncio
async def test_snooze_expired_token_has_no_partial_write_and_replay_commits_once(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    test_username: str,
) -> None:
    """A rejected snooze can be replayed after auth recovery without a duplicate transition."""
    session, thread = await _pending_roll(async_db)

    _set_access_token(auth_client, test_username, expired=True)
    rejected = await auth_client.post("/api/snooze/")
    assert rejected.status_code == 401

    await async_db.refresh(session)
    assert session.pending_thread_id == thread.id
    assert thread.id not in (session.snoozed_thread_ids or [])
    result = await async_db.execute(
        select(Event).where(Event.session_id == session.id, Event.type == "snooze")
    )
    assert result.scalars().all() == []

    _set_access_token(auth_client, test_username, expired=False)
    replay = await auth_client.post("/api/snooze/")
    assert replay.status_code == 200

    duplicate = await auth_client.post("/api/snooze/")
    assert duplicate.status_code == 400

    await async_db.refresh(session)
    assert session.pending_thread_id is None
    assert thread.id in (session.snoozed_thread_ids or [])
    result = await async_db.execute(
        select(Event).where(Event.session_id == session.id, Event.type == "snooze")
    )
    snooze_events = result.scalars().all()
    assert len(snooze_events) == 1
    assert snooze_events[0].thread_id == thread.id
