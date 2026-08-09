"""Regression coverage for the canonical browser authentication contract."""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_two_clients_for_one_user_refresh_independently(
    client: AsyncClient,
) -> None:
    """Independent browser sessions for one user must not invalidate each other.

    Args:
        client: Authenticated HTTP client representing the first browser session.

    Returns:
        None: Assertions verify independent refresh and logout isolation.
    """
    credentials = {
        "username": "multi-client-user",
        "email": "multi-client@example.com",
        "password": "password123",
    }
    register_response = await client.post("/api/v1/auth/register", json=credentials)
    assert register_response.status_code == 200

    login_payload = {"username": credentials["username"], "password": credentials["password"]}
    first_login = await client.post("/api/v1/auth/login", json=login_payload)
    assert first_login.status_code == 200

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as second_client:
        second_login = await second_client.post("/api/v1/auth/login", json=login_payload)
        assert second_login.status_code == 200

        first_refresh = await client.post("/api/v1/auth/refresh")
        second_refresh = await second_client.post("/api/v1/auth/refresh")
        assert first_refresh.status_code == 200
        assert second_refresh.status_code == 200

        first_access = first_refresh.json()["access_token"]
        first_logout = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {first_access}"},
        )
        assert first_logout.status_code == 200

        second_refresh_after_first_logout = await second_client.post("/api/v1/auth/refresh")
        assert second_refresh_after_first_logout.status_code == 200


def test_frontend_does_not_use_legacy_auth_surface() -> None:
    """Maintained frontend code must use only the canonical /v1/auth family.

    Returns:
        None: Assertion fails if legacy /auth/ routes are found in maintained code.
    """
    frontend_root = Path("frontend/src")
    offenders: list[str] = []
    for path in frontend_root.rglob("*"):
        if path.suffix not in {".js", ".jsx", ".ts", ".tsx"}:
            continue
        text = path.read_text(encoding="utf-8")
        if any(f"{quote}/auth/" in text for quote in ("'", '"', "`")):
            offenders.append(str(path))

    assert offenders == [], f"Legacy auth routes found in maintained frontend: {offenders}"
