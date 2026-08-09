"""Regression coverage for secret-free authentication reason diagnostics."""

import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Request
from httpx import AsyncClient
from jose import jwt

from app.auth import ALGORITHM, SECRET_KEY
from app.csrf import log_csrf_rejection


def _auth_reasons(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Return structured authentication reason codes captured by the test logger."""
    return [
        record.auth_reason
        for record in caplog.records
        if hasattr(record, "auth_reason")
    ]


@pytest.mark.asyncio
async def test_refresh_logs_missing_cookie_without_secrets(
    client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A browser refresh without its HttpOnly cookie has an explicit reason code."""
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
    """Expired refresh credentials are distinguishable from generic invalid tokens."""
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
    """Malformed refresh credentials emit the stable invalid-token reason code."""
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
    """Successful and independently revoked browser refreshes remain distinguishable."""
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
    logout_response = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert logout_response.status_code == 200

    revoked_response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert revoked_response.status_code == 401
    assert "revoked_token" in _auth_reasons(caplog)
    assert refresh_token not in caplog.text


def test_csrf_rejection_logs_reason_without_credentials(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """CSRF middleware diagnostics identify the rejection without logging credentials."""
    caplog.set_level(logging.WARNING)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "https",
            "path": "/api/v1/auth/logout",
            "raw_path": b"/api/v1/auth/logout",
            "query_string": b"",
            "headers": [(b"authorization", b"Bearer secret-value")],
            "client": ("127.0.0.1", 1234),
            "server": ("test", 443),
        }
    )
    request.state.request_id = "request-123"

    log_csrf_rejection(request)

    assert "csrf_rejected" in _auth_reasons(caplog)
    assert "secret-value" not in caplog.text
    record = next(record for record in caplog.records if hasattr(record, "auth_reason"))
    assert record.request_id == "request-123"
    assert record.path == "/api/v1/auth/logout"
