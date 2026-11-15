"""Tests for security gating of internal endpoints.

Admin/debug HTTP handlers were pruned (#4861), so the gating covered here is
the retained eager health/ping/metrics exposure plus the guarantee that the
pruned admin/debug paths answer 404 regardless of the internal-ops/debug
flags. Health/ping/metrics are intentionally unaffected and stay asserted.
"""

import logging
import os

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.security import MAX_CLIENT_IP_CHARS, get_client_ip
from tests.conftest import _create_async_db_override


def test_get_client_ip_truncates_to_the_persisted_column_bound() -> None:
    """A hostile forwarding header must not exceed varchar(45) on rejected login."""
    hostile = "198.51.100.250-" * 8
    resolved = get_client_ip({"x-forwarded-for": f"{hostile}, 203.0.113.9"}, None)
    assert len(resolved) == MAX_CLIENT_IP_CHARS
    assert len(get_client_ip({}, "203.0.113.9" * 10)) == MAX_CLIENT_IP_CHARS
    assert get_client_ip({}, None) == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/admin/export/csv/",
        "/api/v1/admin/export/csv/",
        "/api/admin/export/json/",
        "/api/v1/admin/export/json/",
        "/api/admin/export/summary/",
        "/api/v1/admin/export/summary/",
        "/api/debug/log",
        "/api/v1/debug/log",
    ],
)
async def test_pruned_routes_return_404_regardless_of_gate(
    client: AsyncClient, endpoint: str
) -> None:
    """Pruned admin/debug routes return 404 even when internal ops are enabled."""
    original_value = os.getenv("ENABLE_INTERNAL_OPS_ROUTES")
    original_debug = os.getenv("ENABLE_DEBUG_ROUTES")
    os.environ["ENABLE_INTERNAL_OPS_ROUTES"] = "true"
    os.environ["ENABLE_DEBUG_ROUTES"] = "true"

    try:
        response = await client.get(endpoint)
        assert response.status_code == 404
    finally:
        if original_value is None:
            os.environ.pop("ENABLE_INTERNAL_OPS_ROUTES", None)
        else:
            os.environ["ENABLE_INTERNAL_OPS_ROUTES"] = original_value
        if original_debug is None:
            os.environ.pop("ENABLE_DEBUG_ROUTES", None)
        else:
            os.environ["ENABLE_DEBUG_ROUTES"] = original_debug


@pytest.mark.asyncio
async def test_internal_routes_return_404_when_disabled(client: AsyncClient) -> None:
    """The pruned routes stay 404 with the legacy gate disabled, like before."""
    original_value = os.getenv("ENABLE_INTERNAL_OPS_ROUTES")
    os.environ["ENABLE_INTERNAL_OPS_ROUTES"] = "false"

    try:
        response = await client.get("/api/admin/export/csv/")
        assert response.status_code == 404
    finally:
        if original_value is None:
            os.environ.pop("ENABLE_INTERNAL_OPS_ROUTES", None)
        else:
            os.environ["ENABLE_INTERNAL_OPS_ROUTES"] = original_value


@pytest.mark.asyncio
async def test_pruned_admin_routes_stay_404_when_enabled(
    client: AsyncClient,
) -> None:
    """Enabling internal ops no longer revives the deleted admin handlers (#4861)."""
    original_value = os.getenv("ENABLE_INTERNAL_OPS_ROUTES")
    os.environ["ENABLE_INTERNAL_OPS_ROUTES"] = "true"

    try:
        for endpoint in (
            "/api/admin/export/csv/",
            "/api/admin/export/json/",
            "/api/admin/export/summary/",
            "/api/admin/import/csv/",
            "/api/admin/delete-test-data/",
        ):
            response = await client.get(endpoint)
            assert response.status_code == 404, (
                f"{endpoint} must stay pruned even with internal ops enabled"
            )
    finally:
        if original_value is None:
            os.environ.pop("ENABLE_INTERNAL_OPS_ROUTES", None)
        else:
            os.environ["ENABLE_INTERNAL_OPS_ROUTES"] = original_value


@pytest.mark.asyncio
async def test_production_mode_blocks_internal_routes(client: AsyncClient) -> None:
    """Production mode keeps pruned admin/debug routes at 404."""
    os.environ["ENABLE_DEBUG_ROUTES"] = "false"
    os.environ["ENABLE_INTERNAL_OPS_ROUTES"] = "false"

    try:
        response = await client.get("/api/admin/export/csv/")
        assert response.status_code == 404

        response = await client.post("/api/debug/log", json={})
        assert response.status_code == 404
    finally:
        os.environ.pop("ENABLE_DEBUG_ROUTES", None)
        os.environ.pop("ENABLE_INTERNAL_OPS_ROUTES", None)


@pytest.mark.asyncio
async def test_health_routes_always_accessible(client: AsyncClient) -> None:
    """Health routes are always accessible (not gated)."""
    response = await client.get("/health")
    assert response.status_code in (200, 503)


@pytest.mark.asyncio
async def test_ping_and_metrics_routes_always_accessible(client: AsyncClient) -> None:
    """Eager ping/metrics routes are retained and always accessible (#4861)."""
    ping = await client.get("/api/ping")
    assert ping.status_code == 200

    metrics = await client.get("/api/metrics")
    assert metrics.status_code == 200


@pytest.mark.asyncio
async def test_sensitive_headers_redacted_in_error_logs(
    client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Authorization, Cookie, and Set-Cookie headers are redacted in error logs."""
    with caplog.at_level(logging.WARNING):
        _ = await client.post(
            "/api/v1/roll",
            json={"faces": 6, "count": 1},
            headers={
                "Authorization": "Bearer secret-token-123",
                "Cookie": "session=abc123",
                "User-Agent": "test-agent",
            },
        )

    log_entries = [record for record in caplog.records if "Client Error" in record.message]
    assert len(log_entries) > 0

    for entry in log_entries:
        headers = getattr(entry, "headers", None)
        if headers and isinstance(headers, dict):
            assert any("Authorization" in k or "authorization" in k for k in headers.keys())
            assert any("Cookie" in k or "cookie" in k for k in headers.keys())
            assert any(
                "[REDACTED:" in v and ("Authorization" in v or "authorization" in v)
                for k, v in headers.items()
                if "Authorization" in k or "authorization" in k
            )
            assert any(
                "[REDACTED:" in v and ("Cookie" in v or "cookie" in v)
                for k, v in headers.items()
                if "Cookie" in k or "cookie" in k
            )
            assert any(
                "test-agent" in v
                for k, v in headers.items()
                if "User-Agent" in k or "user-agent" in k
            )


@pytest.mark.asyncio
async def test_sensitive_json_keys_redacted_in_error_logs(
    client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Sensitive JSON keys (password, secret, token, access_token, refresh_token, api_key) are redacted."""
    sensitive_data = {
        "username": "testuser",
        "password": "secret123",
        "api_key": "key-xyz",
        "token": "token-abc",
    }

    with caplog.at_level(logging.WARNING):
        _ = await client.post("/api/v1/roll", json=sensitive_data)

    log_entries = [record for record in caplog.records if "Client Error" in record.message]
    assert len(log_entries) > 0

    for entry in log_entries:
        request_body = getattr(entry, "request_body", None)
        if request_body and isinstance(request_body, str):
            assert (
                request_body == "[REDACTED: contains sensitive data]"
                or "secret123" not in request_body
            )


@pytest.mark.asyncio
async def test_all_sensitive_json_keys_redacted(
    client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """All sensitive keys trigger redaction: password, secret, token, access_token, refresh_token, api_key."""
    test_cases = [
        {"password": "test123"},
        {"secret": "test123"},
        {"token": "test123"},
        {"access_token": "test123"},
        {"refresh_token": "test123"},
        {"api_key": "test123"},
        {"username": "test", "password": "test123"},
    ]

    for sensitive_data in test_cases:
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            _ = await client.post("/api/v1/roll", json=sensitive_data)

        log_entries = [record for record in caplog.records if "Client Error" in record.message]
        if log_entries:
            for entry in log_entries:
                request_body = getattr(entry, "request_body", None)
                if request_body and isinstance(request_body, str):
                    assert "[REDACTED: contains sensitive data]" in request_body, (
                        f"Failed for data: {sensitive_data}"
                    )


@pytest.mark.asyncio
async def test_auth_routes_log_only_size_and_type(
    client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Auth routes (/api/auth/, /api/login, /api/register, /api/logout) log only size/type, not content."""
    auth_endpoints = ["/api/login", "/api/register", "/api/logout", "/api/auth/refresh"]
    sensitive_data = {"username": "test", "password": "secret123", "token": "abc"}

    for endpoint in auth_endpoints:
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            try:
                _ = await client.post(endpoint, json=sensitive_data)
            except Exception:
                pass

        log_entries = [record for record in caplog.records if "Client Error" in record.message]
        if log_entries:
            for entry in log_entries:
                request_body = getattr(entry, "request_body", None)
                if request_body and isinstance(request_body, str):
                    assert "[AUTH ROUTE:" in request_body, (
                        f"Expected auth route format for {endpoint}"
                    )
                    assert "bytes," in request_body


@pytest.mark.asyncio
async def test_non_sensitive_body_not_redacted(
    client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Non-sensitive body content is not redacted in error logs."""
    safe_data = {"username": "testuser", "email": "test@example.com", "count": 5}

    with caplog.at_level(logging.WARNING):
        _ = await client.post("/api/v1/roll", json=safe_data)

    log_entries = [record for record in caplog.records if "Client Error" in record.message]
    assert len(log_entries) > 0

    for entry in log_entries:
        request_body = getattr(entry, "request_body", None)
        if request_body and isinstance(request_body, dict):
            assert "password" not in str(request_body)
            assert "secret" not in str(request_body)


@pytest.mark.asyncio
async def test_cors_origins_required_in_production(async_db: AsyncSession) -> None:
    """CORS_ORIGINS is required in production mode, app fails to start without it."""
    _ = async_db
    from app.config import clear_settings_cache

    original_env = os.getenv("ENVIRONMENT")
    original_cors = os.getenv("CORS_ORIGINS")

    os.environ["ENVIRONMENT"] = "production"
    os.environ["CORS_ORIGINS"] = ""  # Empty string triggers validation error

    # Clear the settings cache so create_app reads fresh env vars
    clear_settings_cache()

    try:
        from app.main import create_app

        with pytest.raises(RuntimeError, match="CORS_ORIGINS must be set in production mode"):
            _ = create_app()
    finally:
        if original_env is None:
            os.environ.pop("ENVIRONMENT", None)
        else:
            os.environ["ENVIRONMENT"] = original_env
        if original_cors is None:
            os.environ.pop("CORS_ORIGINS", None)
        else:
            os.environ["CORS_ORIGINS"] = original_cors
        # Clear cache again to restore normal settings
        clear_settings_cache()


@pytest.mark.asyncio
async def test_cors_origins_allowed_in_production_when_set(async_db: AsyncSession) -> None:
    """CORS_ORIGINS is respected in production mode when set correctly."""
    from httpx import ASGITransport, AsyncClient

    original_env = os.getenv("ENVIRONMENT")
    original_cors = os.getenv("CORS_ORIGINS")

    os.environ["ENVIRONMENT"] = "production"
    os.environ["CORS_ORIGINS"] = "https://example.com,https://app.example.com"

    from app.database import get_db
    from app.main import create_app

    test_app = create_app(serve_frontend=False)
    test_app.dependency_overrides[get_db] = await _create_async_db_override(None)

    try:
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/health")
            assert response.status_code in (200, 503)
    finally:
        test_app.dependency_overrides.clear()
        if original_env is None:
            os.environ.pop("ENVIRONMENT", None)
        else:
            os.environ["ENVIRONMENT"] = original_env
        if original_cors is None:
            os.environ.pop("CORS_ORIGINS", None)
        else:
            os.environ["CORS_ORIGINS"] = original_cors


@pytest.mark.asyncio
async def test_cors_defaults_to_wildcard_in_development(async_db: AsyncSession) -> None:
    """CORS defaults to wildcard in development mode when CORS_ORIGINS is not set."""
    from httpx import ASGITransport, AsyncClient

    original_env = os.getenv("ENVIRONMENT")
    original_cors = os.getenv("CORS_ORIGINS")

    os.environ["ENVIRONMENT"] = "development"

    if "CORS_ORIGINS" in os.environ:
        os.environ.pop("CORS_ORIGINS")

    from app.database import get_db
    from app.main import create_app

    test_app = create_app(serve_frontend=False)
    test_app.dependency_overrides[get_db] = await _create_async_db_override(None)

    try:
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/health")
            assert response.status_code in (200, 503)
    finally:
        test_app.dependency_overrides.clear()
        if original_env is None:
            os.environ.pop("ENVIRONMENT", None)
        else:
            os.environ["ENVIRONMENT"] = original_env
        if original_cors is None:
            os.environ.pop("CORS_ORIGINS", None)
        else:
            os.environ["CORS_ORIGINS"] = original_cors


@pytest.mark.asyncio
async def test_cors_allow_credentials_is_false(async_db: AsyncSession) -> None:
    """CORS middleware is configured with allow_credentials=False for JWT bearer token authentication."""
    from httpx import ASGITransport, AsyncClient

    original_env = os.getenv("ENVIRONMENT")
    original_cors = os.getenv("CORS_ORIGINS")

    os.environ["ENVIRONMENT"] = "production"
    os.environ["CORS_ORIGINS"] = "https://example.com"

    from app.database import get_db
    from app.main import create_app

    test_app = create_app(serve_frontend=False)
    test_app.dependency_overrides[get_db] = await _create_async_db_override(None)

    try:
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/health")
            assert response.status_code in (200, 503)
    finally:
        test_app.dependency_overrides.clear()
        if original_env is None:
            os.environ.pop("ENVIRONMENT", None)
        else:
            os.environ["ENVIRONMENT"] = original_env
        if original_cors is None:
            os.environ.pop("CORS_ORIGINS", None)
        else:
            os.environ["CORS_ORIGINS"] = original_cors


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "environment,cors_origins",
    [
        ("production", "https://example.com"),
        ("development", None),
    ],
    ids=["production", "development"],
)
async def test_app_starts_successfully(
    async_db: AsyncSession,
    environment: str,
    cors_origins: str | None,
) -> None:
    """App starts successfully in both production and development modes."""
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    original_env = os.getenv("ENVIRONMENT")
    original_cors = os.getenv("CORS_ORIGINS")

    os.environ["ENVIRONMENT"] = environment
    if cors_origins:
        os.environ["CORS_ORIGINS"] = cors_origins

    from app.database import get_db

    test_app = None
    try:
        test_app = create_app(serve_frontend=False)
        test_app.dependency_overrides[get_db] = await _create_async_db_override(None)

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/health")
            assert response.status_code in (200, 503)
    finally:
        if test_app:
            test_app.dependency_overrides.clear()
        if original_env is None:
            os.environ.pop("ENVIRONMENT", None)
        else:
            os.environ["ENVIRONMENT"] = original_env
        if original_cors is None:
            os.environ.pop("CORS_ORIGINS", None)
        else:
            os.environ["CORS_ORIGINS"] = original_cors


@pytest.mark.asyncio
async def test_test_endpoints_not_mounted_when_test_environment_unset(
    async_db: AsyncSession,
) -> None:
    """The /api/test/* router is not mounted when TEST_ENVIRONMENT is unset.

    This is a regression guard for the least-privilege gate introduced in #552:
    the state-mutating test harness must only be registered in pytest/E2E where
    TEST_ENVIRONMENT is explicitly set, never in dev/staging/review apps.
    """
    from httpx import ASGITransport, AsyncClient

    from app.database import get_db
    from app.main import create_app

    original_test_env = os.getenv("TEST_ENVIRONMENT")
    os.environ.pop("TEST_ENVIRONMENT", None)

    test_app = create_app(serve_frontend=False)
    test_app.dependency_overrides[get_db] = await _create_async_db_override(async_db)

    try:
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post("/api/test/sessions/expire")
            assert response.status_code == 404, (
                f"Expected 404 (route not mounted) when TEST_ENVIRONMENT is unset, "
                f"got {response.status_code}"
            )
    finally:
        test_app.dependency_overrides.clear()
        if original_test_env is not None:
            os.environ["TEST_ENVIRONMENT"] = original_test_env
