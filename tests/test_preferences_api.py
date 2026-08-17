"""Tests for user preferences API endpoints (issue #1398)."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import DEFAULT_THEME, SUPPORTED_THEMES


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
