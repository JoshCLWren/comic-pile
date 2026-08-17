"""Single-round-trip auth regression coverage for issue #1261.

Every authenticated request previously ran two sequential database reads
before endpoint logic: a revoked-token lookup by JTI and then a user lookup
by username. ``get_current_user`` now resolves both with one LEFT JOIN query.

Before: 2 SELECTs per authenticated request.
After: 1 SELECT per authenticated request.
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
    """Yield a list that records SELECT statements executed on the engine."""
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
async def test_authenticated_request_uses_single_auth_query(
    auth_client: AsyncClient,
    db_engine: AsyncEngine,
) -> None:
    """An authenticated request resolves auth with exactly one SELECT."""
    with _captured_selects(db_engine) as select_statements:
        response = await auth_client.get("/api/auth/me")

    assert response.status_code == 200
    assert len(select_statements) == 1, select_statements
    assert "join" in select_statements[0].lower()


@pytest.mark.asyncio
async def test_revoked_access_token_is_rejected(auth_client: AsyncClient) -> None:
    """A revoked access token is rejected after the single-query change."""
    logout_response = await auth_client.post("/api/auth/logout")
    assert logout_response.status_code == 200

    response = await auth_client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "Token has been revoked"


@pytest.mark.asyncio
async def test_deleted_user_token_is_rejected(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    test_username: str,
) -> None:
    """A token for a deleted user is rejected after the single-query change."""
    await async_db.execute(delete(User).where(User.username == test_username))
    await async_db.flush()

    response = await auth_client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "User not found"
