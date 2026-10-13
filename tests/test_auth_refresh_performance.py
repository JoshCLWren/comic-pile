"""Tests verifying the optimized auth refresh endpoint.

The refresh endpoint was optimized to use a single combined database query
(``get_user_by_username_with_revocation_check``) instead of separate
``is_token_revoked`` + ``get_user_by_username`` calls, matching the
single-round-trip pattern already established by ``get_current_user``.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine


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


@pytest.mark.asyncio
async def test_refresh_uses_single_combined_query(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """The refresh endpoint resolves user + revocation status with one SELECT.

    Previously the endpoint issued separate ``is_token_revoked`` and
    ``get_user_by_username`` queries (two SELECTs). The optimization
    consolidates them into a single LEFT JOIN query.
    """
    user_data = {
        "username": "refreshqueryuser",
        "email": "refreshquery@example.com",
        "password": "password123",
    }
    response = await client.post("/api/v1/auth/register", json=user_data)
    assert response.status_code == 200

    login_data = {"username": "refreshqueryuser", "password": "password123"}
    response = await client.post("/api/v1/auth/login", json=login_data)
    assert response.status_code == 200
    old_tokens = response.json()

    refresh_data = {"refresh_token": old_tokens["refresh_token"]}
    with _captured_selects(db_engine) as select_statements:
        response = await client.post("/api/v1/auth/refresh", json=refresh_data)

    assert response.status_code == 200
    assert len(select_statements) == 1, f"Expected 1 SELECT, got: {select_statements}"


@pytest.mark.asyncio
async def test_refresh_revoked_token_rejected(
    client: AsyncClient,
) -> None:
    """A revoked refresh token is rejected with 401.

    Both access and refresh tokens share the same JTI, so revoking the
    access token via logout also invalidates the refresh token.
    """
    user_data = {
        "username": "revokedrefreshuser",
        "email": "revokedrefresh@example.com",
        "password": "password123",
    }
    response = await client.post("/api/v1/auth/register", json=user_data)
    assert response.status_code == 200

    login_data = {"username": "revokedrefreshuser", "password": "password123"}
    response = await client.post("/api/v1/auth/login", json=login_data)
    assert response.status_code == 200
    tokens = response.json()

    refresh_response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refresh_response.status_code == 200

    access_token = refresh_response.json()["access_token"]
    csrf_response = await client.get("/api/v1/auth/csrf")
    csrf_token = csrf_response.json()["csrf_token"]

    logout_response = await client.post(
        "/api/v1/auth/logout",
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-CSRF-Token": csrf_token,
        },
    )
    assert logout_response.status_code == 200

    refresh_token = tokens["refresh_token"]
    revoked_response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert revoked_response.status_code == 401
    assert "revoked" in revoked_response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_refresh_returns_new_tokens(
    client: AsyncClient,
) -> None:
    """Successful refresh returns new access and refresh tokens."""
    user_data = {
        "username": "newtokenuser",
        "email": "newtoken@example.com",
        "password": "password123",
    }
    response = await client.post("/api/v1/auth/register", json=user_data)
    assert response.status_code == 200

    login_data = {"username": "newtokenuser", "password": "password123"}
    response = await client.post("/api/v1/auth/login", json=login_data)
    assert response.status_code == 200
    old_tokens = response.json()

    refresh_data = {"refresh_token": old_tokens["refresh_token"]}
    response = await client.post("/api/v1/auth/refresh", json=refresh_data)
    assert response.status_code == 200

    new_tokens = response.json()
    assert "access_token" in new_tokens
    assert "refresh_token" in new_tokens
    assert new_tokens["token_type"] == "bearer"
    assert new_tokens["access_token"] != old_tokens["access_token"]
    assert new_tokens["refresh_token"] != old_tokens["refresh_token"]
