"""Regression coverage for secret-free authentication reason diagnostics."""

import logging
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ALGORITHM, SECRET_KEY
from app.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from app.database import get_db
from app.main import app
from tests.conftest import _create_async_db_override


def _auth_reasons(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Return structured authentication reason codes captured by the test logger."""
    return [
        str(record.__dict__["auth_reason"])
        for record in caplog.records
        if "auth_reason" in record.__dict__
    ]


@pytest.mark.asyncio
async def test_refresh_logs_missing_cookie_without_secrets(
    client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A browser refresh without its HttpOnly cookie has an explicit reason code.

    Args:
        client: Async application client backed by the PostgreSQL test database.
        caplog: Pytest log-capture fixture.

    Returns:
        None.
    """
    caplog.set_level(logging.WARNING)
    client.cookies.clear()

    response = await client.post("/api/v1/auth/refresh")

    assert response.status_code == 401
    assert "missing_cookie" in _auth_reasons(caplog)
    assert "refresh_token" not in caplog.text


@pytest.mark.asyncio
async def test_refresh_logs_expired_token_without_secrets(
    client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Expired refresh credentials are distinguishable from generic invalid tokens.

    Args:
        client: Async application client backed by the PostgreSQL test database.
        caplog: Pytest log-capture fixture.

    Returns:
        None.
    """
    caplog.set_level(logging.WARNING)
    expired_token = jwt.encode(
        {
            "sub": "expired-user",
            "jti": "expired-jti",
            "type": "refresh",
            "exp": datetime.now(UTC) - timedelta(minutes=1),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )

    response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": expired_token},
    )

    assert response.status_code == 401
    assert "expired_token" in _auth_reasons(caplog)
    assert expired_token not in caplog.text


@pytest.mark.asyncio
async def test_refresh_logs_invalid_token_without_secrets(
    client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Malformed refresh credentials emit the stable invalid-token reason code.

    Args:
        client: Async application client backed by the PostgreSQL test database.
        caplog: Pytest log-capture fixture.

    Returns:
        None.
    """
    caplog.set_level(logging.WARNING)
    invalid_token = "not-a-valid-jwt"

    response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": invalid_token},
    )

    assert response.status_code == 401
    assert "invalid_token" in _auth_reasons(caplog)
    assert invalid_token not in caplog.text


@pytest.mark.asyncio
async def test_refresh_logs_revoked_token_and_success(
    client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Successful and independently revoked browser refreshes remain distinguishable.

    Args:
        client: Async application client backed by the PostgreSQL test database.
        caplog: Pytest log-capture fixture.

    Returns:
        None.
    """
    caplog.set_level(logging.WARNING)
    register_response = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "auth-log-user",
            "email": "auth-log-user@example.com",
            "password": "password123",
        },
    )
    assert register_response.status_code == 200

    refresh_response = await client.post("/api/v1/auth/refresh")
    assert refresh_response.status_code == 200
    assert "refreshed" in _auth_reasons(caplog)

    access_token = refresh_response.json()["access_token"]
    refresh_token = refresh_response.json()["refresh_token"]
    csrf_response = await client.get("/api/v1/auth/csrf")
    assert csrf_response.status_code == 200
    csrf_token = csrf_response.json()["csrf_token"]
    logout_response = await client.post(
        "/api/v1/auth/logout",
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-CSRF-Token": csrf_token,
        },
    )
    assert logout_response.status_code == 200

    revoked_response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert revoked_response.status_code == 401
    assert "revoked_token" in _auth_reasons(caplog)
    assert refresh_token not in caplog.text


@pytest.mark.asyncio
async def test_csrf_middleware_logs_rejection_without_credentials(
    async_db: AsyncSession,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The middleware logs rejected auth mutations before returning 403.

    Args:
        async_db: Async SQLAlchemy session backed by the PostgreSQL test database.
        caplog: Pytest log-capture fixture.
        monkeypatch: Environment patch helper used to exercise production CSRF behavior.

    Returns:
        None.
    """
    caplog.set_level(logging.WARNING)
    monkeypatch.delenv("TEST_ENVIRONMENT", raising=False)

    app.dependency_overrides[get_db] = await _create_async_db_override(async_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        secret_value = "Bearer secret-value"

        response = await ac.post(
            "/api/v1/auth/logout",
            headers={"Authorization": secret_value},
        )

    assert response.status_code == 403
    assert "csrf_rejected" in _auth_reasons(caplog)
    assert "secret-value" not in caplog.text
    record = next(record for record in caplog.records if "auth_reason" in record.__dict__)
    assert record.__dict__["path"] == "/api/v1/auth/logout"
    assert record.__dict__["auth_outcome"] == "rejected"
    assert record.__dict__["event"] == "auth_csrf"


@pytest.mark.asyncio
async def test_csrf_middleware_allows_matching_token(
    client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A protected auth mutation succeeds when cookie and header CSRF tokens match.

    Args:
        client: Async application client backed by the PostgreSQL test database.
        caplog: Pytest log-capture fixture.
        monkeypatch: Environment patch helper used to exercise production CSRF behavior.

    Returns:
        None.
    """
    caplog.set_level(logging.WARNING)
    monkeypatch.delenv("TEST_ENVIRONMENT", raising=False)
    csrf_response = await client.get("/api/v1/auth/csrf")
    assert csrf_response.status_code == 200
    csrf_token = csrf_response.json()["csrf_token"]

    response = await client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 200
    assert response.json() == {"message": "Successfully logged out"}
    assert "csrf_rejected" not in _auth_reasons(caplog)
