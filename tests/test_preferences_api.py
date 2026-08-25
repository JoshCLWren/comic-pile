"""Tests for user preferences API endpoints (issue #1398)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from app.auth import create_access_token
from app.constants import DEFAULT_THEME, SUPPORTED_THEMES
from app.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token
from app.database import get_db
from app.main import app
from app.models import User, UserPreferences


@pytest.mark.asyncio
async def test_get_preferences_returns_default_when_no_row(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Resolve to the default theme when no preference row exists.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
    """
    response = await auth_client.get("/api/v1/users/me/preferences")
    assert response.status_code == 200

    data = response.json()
    assert data["theme"] == DEFAULT_THEME
    assert isinstance(data["user_id"], int)


@pytest.mark.asyncio
async def test_patch_preferences_creates_row_and_sets_theme(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Create a new preferences row and return the persisted value.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
    """
    response = await auth_client.patch(
        "/api/v1/users/me/preferences",
        json={"theme": "ink-gold"},
    )
    assert response.status_code == 200

    data = response.json()
    assert data["theme"] == "ink-gold"
    assert isinstance(data["user_id"], int)


@pytest.mark.asyncio
async def test_patch_preferences_updates_existing_row(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Update an existing row when called twice with different themes.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
    """
    await auth_client.patch(
        "/api/v1/users/me/preferences",
        json={"theme": "ink-gold"},
    )

    response = await auth_client.patch(
        "/api/v1/users/me/preferences",
        json={"theme": "command-center"},
    )
    assert response.status_code == 200

    data = response.json()
    assert data["theme"] == "command-center"


@pytest.mark.asyncio
async def test_get_preferences_returns_persisted_theme(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Return the theme that was previously persisted via PATCH.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
    """
    await auth_client.patch(
        "/api/v1/users/me/preferences",
        json={"theme": "command-center"},
    )

    response = await auth_client.get("/api/v1/users/me/preferences")
    assert response.status_code == 200
    assert response.json()["theme"] == "command-center"


@pytest.mark.asyncio
async def test_patch_preferences_no_op_when_theme_is_none(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """PATCH with theme=null leaves the current preference unchanged.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
    """
    await auth_client.patch(
        "/api/v1/users/me/preferences",
        json={"theme": "ink-gold"},
    )

    response = await auth_client.patch(
        "/api/v1/users/me/preferences",
        json={"theme": None},
    )
    assert response.status_code == 200
    assert response.json()["theme"] == "ink-gold"


@pytest.mark.asyncio
async def test_patch_preferences_rejects_invalid_theme(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """PATCH with an unknown theme id returns 422 validation error.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
    """
    response = await auth_client.patch(
        "/api/v1/users/me/preferences",
        json={"theme": "neon-pink"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_preferences_isolation_between_users(
    client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """One user's preference change does not affect another user.

    Args:
        client: Unauthenticated HTTP client.
        async_db: Async database session for direct database queries.
    """
    from datetime import UTC, datetime

    from app.auth import create_access_token
    from app.models import User

    now = datetime.now(UTC)

    user_a = User(username="pref_test_user_a", created_at=now)
    async_db.add(user_a)
    await async_db.commit()
    await async_db.refresh(user_a)

    user_b = User(username="pref_test_user_b", created_at=now)
    async_db.add(user_b)
    await async_db.commit()
    await async_db.refresh(user_b)

    token_a = create_access_token(data={"sub": user_a.username, "jti": "test-a"})
    token_b = create_access_token(data={"sub": user_b.username, "jti": "test-b"})

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    resp_a = await client.patch(
        "/api/v1/users/me/preferences",
        json={"theme": "ink-gold"},
        headers=headers_a,
    )
    assert resp_a.status_code == 200
    assert resp_a.json()["theme"] == "ink-gold"

    resp_b = await client.get("/api/v1/users/me/preferences", headers=headers_b)
    assert resp_b.status_code == 200
    assert resp_b.json()["theme"] == DEFAULT_THEME


@pytest.mark.asyncio
async def test_unauthenticated_get_preferences_returns_401(
    client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """GET without auth returns 401 or 403.

    Args:
        client: Unauthenticated HTTP client.
        async_db: Async database session for direct database queries.
    """
    response = await client.get("/api/v1/users/me/preferences")
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_unauthenticated_patch_preferences_returns_401(
    client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """PATCH without auth returns 401 or 403.

    Args:
        client: Unauthenticated HTTP client.
        async_db: Async database session for direct database queries.
    """
    response = await client.patch(
        "/api/v1/users/me/preferences",
        json={"theme": "ink-gold"},
    )
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_all_supported_themes_accepted(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Every theme id in SUPPORTED_THEMES is accepted by the PATCH endpoint.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
    """
    for theme_id in SUPPORTED_THEMES:
        response = await auth_client.patch(
            "/api/v1/users/me/preferences",
            json={"theme": theme_id},
        )
        assert response.status_code == 200, f"Theme {theme_id!r} was rejected"
        assert response.json()["theme"] == theme_id


@pytest.mark.asyncio
async def test_patch_empty_body_returns_default(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """PATCH with an empty body creates the row with defaults.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
    """
    response = await auth_client.patch(
        "/api/v1/users/me/preferences",
        json={},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["theme"] == DEFAULT_THEME


@pytest.mark.asyncio
async def test_concurrent_first_theme_writes_all_succeed(
    db_engine: AsyncEngine,
    async_db_committed: AsyncSession,
) -> None:
    """Overlapping first-time theme writes must all succeed (issue #1872).

    Rapid theme changes used to race on select-then-insert: two overlapping
    PATCHes both observed no preference row and one INSERT hit the unique
    constraint, which the database dependency surfaces to users as a 503
    while changing themes. The atomic upsert must tolerate interleaved
    first writes and leave one consistent persisted value behind.

    Args:
        db_engine: Shared test database engine for per-request sessions.
        async_db_committed: Session with real commits so per-request sessions
            can observe the fixture user.
    """
    user = User(username="pref_race_user", created_at=datetime.now(UTC))
    async_db_committed.add(user)
    await async_db_committed.commit()
    await async_db_committed.refresh(user)

    token = create_access_token(data={"sub": user.username, "jti": "pref-race"})
    csrf_token = generate_csrf_token()

    session_maker = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        # A fresh session per request so the gathered requests genuinely
        # interleave against separate connections instead of sharing one
        # identity map through the standard auth_client override.
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    themes = ["ink-gold", "command-center", "classic", "command-center"]
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            ac.cookies.set(CSRF_COOKIE_NAME, csrf_token)
            responses = await asyncio.gather(
                *[
                    ac.patch(
                        "/api/v1/users/me/preferences",
                        json={"theme": theme},
                        headers={
                            "Authorization": f"Bearer {token}",
                            CSRF_HEADER_NAME: csrf_token,
                        },
                    )
                    for theme in themes
                ]
            )
    finally:
        app.dependency_overrides.clear()

    statuses = [response.status_code for response in responses]
    assert statuses == [200] * len(themes), (
        f"Concurrent first-time theme writes failed: {statuses}"
    )
    assert [response.json()["theme"] for response in responses] == themes

    result = await async_db_committed.execute(
        select(UserPreferences.theme).where(UserPreferences.user_id == user.id)
    )
    assert result.scalar_one() in themes
