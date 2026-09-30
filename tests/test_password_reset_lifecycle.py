"""Exercise password recovery with populated reading history and real auth tokens."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.auth import hash_password, verify_password
from app.models import Event, Session, Snapshot, User
from app.models.password_reset_token import PasswordResetToken
from app.services.password_reset_service import complete_reset, request_forgot_password


@pytest.mark.asyncio
@pytest.mark.parametrize("production_constraints", [False, True])
async def test_reset_preserves_history_revokes_auth_and_allows_relogin(
    client: AsyncClient, async_db: AsyncSession, production_constraints: bool,
) -> None:
    """A real reset keeps reading data even with production's restrictive foreign keys."""
    user = User(username="reset-history", email="reset-history@example.com",
                password_hash=hash_password("old-password"))
    async_db.add(user)
    await async_db.flush()
    reading = Session(user_id=user.id)
    async_db.add(reading)
    await async_db.flush()
    event = Event(session_id=reading.id, type="roll", die=6, result=1)
    async_db.add(event)
    await async_db.flush()
    snapshot = Snapshot(session_id=reading.id, event_id=event.id,
                        thread_states={}, description="History must survive recovery")
    async_db.add(snapshot)
    await async_db.commit()
    reading_id, event_id, snapshot_id = reading.id, event.id, snapshot.id

    if production_constraints:
        # DDL is rolled back by the enclosing async_db fixture transaction.
        # Production migrated these keys without ON DELETE CASCADE; create_all
        # fixtures otherwise hide the actual 500 and the destructive delete.
        await async_db.execute(text(
            "ALTER TABLE events DROP CONSTRAINT events_session_id_fkey, "
            "ADD CONSTRAINT events_session_id_fkey FOREIGN KEY (session_id) REFERENCES sessions(id)"
        ))
        await async_db.execute(text(
            "ALTER TABLE snapshots DROP CONSTRAINT snapshots_session_id_fkey, "
            "ADD CONSTRAINT snapshots_session_id_fkey FOREIGN KEY (session_id) REFERENCES sessions(id)"
        ))

    login = await client.post("/api/v1/auth/login", json={
        "username": user.username, "password": "old-password",
    })
    assert login.status_code == 200
    old_access = login.json()["access_token"]
    old_refresh = login.json()["refresh_token"]
    handoff = await request_forgot_password(async_db, user.email or "")
    assert handoff is not None
    reset_body = {"token": handoff.reset_token, "new_password": "new-password"}
    response = await client.post("/api/v1/auth/reset-password", json=reset_body)
    assert response.status_code == 200

    # Force database reads: identity-map entries could hide deleted history.
    assert await async_db.scalar(select(Session.id).where(Session.id == reading_id)) == reading_id
    assert await async_db.scalar(select(Event.id).where(Event.id == event_id)) == event_id
    assert await async_db.scalar(select(Snapshot.id).where(Snapshot.id == snapshot_id)) == snapshot_id
    await async_db.refresh(user)
    assert user.password_hash is not None and verify_password("new-password", user.password_hash)
    assert not verify_password("old-password", user.password_hash)
    token = await async_db.scalar(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
    assert token is not None and token.used_at is not None

    assert (await client.post("/api/v1/auth/reset-password", json=reset_body)).status_code == 400
    assert (await client.get("/api/v1/auth/me", headers={
        "Authorization": f"Bearer {old_access}",
    })).status_code == 401
    assert (await client.post("/api/v1/auth/refresh", json={
        "refresh_token": old_refresh,
    })).status_code == 401
    assert (await client.post("/api/v1/auth/login", json={
        "username": user.username, "password": "old-password",
    })).status_code == 401
    new_login = await client.post("/api/v1/auth/login", json={
        "username": user.username, "password": "new-password",
    })
    assert new_login.status_code == 200
    assert (await client.get("/api/v1/auth/me", headers={
        "Authorization": f"Bearer {new_login.json()['access_token']}",
    })).status_code == 200
    assert (await client.post("/api/v1/auth/refresh", json={
        "refresh_token": new_login.json()["refresh_token"],
    })).status_code == 200


@pytest.mark.asyncio
async def test_concurrent_reset_consumes_token_once(
    async_db_committed: AsyncSession, db_engine: AsyncEngine,
) -> None:
    """Concurrent requests cannot both change the password using one reset token."""
    user = User(username="reset-race", email="reset-race@example.com",
                password_hash=hash_password("old-password"))
    async_db_committed.add(user)
    await async_db_committed.commit()
    handoff = await request_forgot_password(async_db_committed, "reset-race@example.com")
    assert handoff is not None
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)

    async def reset(password: str) -> int:
        """Return the actual status from an independent request transaction."""
        async with sessions() as db:
            try:
                await complete_reset(db, handoff.reset_token, password)
                return 200
            except HTTPException as exc:
                await db.rollback()
                return exc.status_code

    assert sorted(await asyncio.gather(reset("first-password"), reset("second-password"))) == [200, 400]


@pytest.mark.asyncio
async def test_expired_and_superseded_tokens_cannot_reset(async_db: AsyncSession) -> None:
    """Expired and superseded links leave the user's password untouched."""
    user = User(username="reset-expired", email="reset-expired@example.com",
                password_hash=hash_password("old-password"))
    async_db.add(user)
    await async_db.commit()
    first = await request_forgot_password(async_db, "reset-expired@example.com")
    second = await request_forgot_password(async_db, "reset-expired@example.com")
    assert first is not None and second is not None
    with pytest.raises(HTTPException) as superseded:
        await complete_reset(async_db, first.reset_token, "new-password")
    assert superseded.value.status_code == 400
    token = await async_db.scalar(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
    assert token is not None
    token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await async_db.commit()
    with pytest.raises(HTTPException) as expired:
        await complete_reset(async_db, second.reset_token, "new-password")
    assert expired.value.status_code == 400
    await async_db.refresh(user)
    assert user.password_hash is not None and verify_password("old-password", user.password_hash)
