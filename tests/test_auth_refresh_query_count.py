"""Single-round-trip refresh regression coverage for issue #3403.

POST /api/v1/auth/refresh previously ran two sequential database reads
before issuing new tokens: a revoked-token lookup by JTI and then a user
lookup by username. The endpoint now resolves both with one LEFT JOIN
query via ``get_user_by_username_with_revocation_check``, matching the
single-round-trip pattern ``get_current_user`` established for #1261.
Each pooled round trip costs budget on the size-2/no-overflow production
pool, so the refresh path must not spend two.

Before: 2 SELECTs per refresh request.
After: 1 SELECT per refresh request.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import User


@contextmanager
def _captured_selects(db_engine: AsyncEngine) -> Iterator[list[str]]:
    """Yield a list that records SELECT statements executed on the engine.

    Args:
        db_engine: The async database engine to listen on.

    Yields:
        A list that is populated with SELECT statement strings.
    """
    select_statements: list[str] = []

    def _capture(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            select_statements.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        yield select_statements
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _capture)


async def _register_user(client: AsyncClient, username: str) -> dict[str, str]:
    """Register a user and return the issued token pair.

    Args:
        client: Async application client backed by the PostgreSQL test database.
        username: Username to register.

    Returns:
        Token response body with access and refresh tokens.
    """
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "password123",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body
    return body


@pytest.mark.asyncio
async def test_refresh_uses_single_combined_query(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """A refresh resolves user plus revocation status with exactly one SELECT."""
    await _register_user(client, "refreshqueryuser")

    with _captured_selects(db_engine) as select_statements:
        response = await client.post("/api/v1/auth/refresh")

    assert response.status_code == 200
    assert len(select_statements) == 1, select_statements
    assert "join" in select_statements[0].lower()


@pytest.mark.asyncio
async def test_refresh_revoked_token_rejected_with_single_query(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """A revoked refresh token is rejected without an extra round trip."""
    tokens = await _register_user(client, "refreshrevokeduser")

    logout_response = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert logout_response.status_code == 200

    with _captured_selects(db_engine) as select_statements:
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Refresh token has been revoked"
    assert len(select_statements) == 1, select_statements


@pytest.mark.asyncio
async def test_refresh_deleted_user_rejected_with_single_query(
    client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """A refresh token for a deleted user is rejected without an extra round trip."""
    await _register_user(client, "refreshdeleteduser")

    await async_db.execute(delete(User).where(User.username == "refreshdeleteduser"))
    await async_db.flush()

    with _captured_selects(db_engine) as select_statements:
        response = await client.post("/api/v1/auth/refresh")

    assert response.status_code == 401
    assert response.json()["detail"] == "User not found"
    assert len(select_statements) == 1, select_statements


@pytest.mark.asyncio
async def test_refresh_returns_rotated_tokens(client: AsyncClient) -> None:
    """A successful refresh rotates both the access and refresh tokens."""
    tokens = await _register_user(client, "refreshrotateduser")

    response = await client.post("/api/v1/auth/refresh")

    assert response.status_code == 200
    rotated = response.json()
    assert rotated["access_token"] != tokens["access_token"]
    assert rotated["refresh_token"] != tokens["refresh_token"]
