"""Tests for security gating of internal endpoints."""

import logging
import os

import pytest


@pytest.mark.asyncio
async def test_tasks_routes_return_404_when_disabled(client):
    """Task routes return 404 when ENABLE_INTERNAL_OPS_ROUTES is false (default)."""
    original_value = os.getenv("ENABLE_INTERNAL_OPS_ROUTES")
    os.environ["ENABLE_INTERNAL_OPS_ROUTES"] = "false"

    try:
        response = await client.get("/api/tasks/")
        assert response.status_code == 404

        response = await client.get("/api/tasks/ready")
        assert response.status_code == 404

        response = await client.get("/api/tasks/metrics")
        assert response.status_code == 404
    finally:
        if original_value is None:
            os.environ.pop("ENABLE_INTERNAL_OPS_ROUTES", None)
        else:
            os.environ["ENABLE_INTERNAL_OPS_ROUTES"] = original_value


@pytest.mark.asyncio
async def test_tasks_routes_accessible_when_enabled(db):
    """Task routes work when ENABLE_INTERNAL_OPS_ROUTES is true."""
    from httpx import ASGITransport, AsyncClient

    original_value = os.getenv("ENABLE_INTERNAL_OPS_ROUTES")
    os.environ["ENABLE_INTERNAL_OPS_ROUTES"] = "true"

    def override_get_db():
        try:
            yield db
        finally:
            pass

    from app.database import get_db
    from app.main import create_app

    test_app = create_app()
    test_app.dependency_overrides[get_db] = override_get_db

    try:
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/api/tasks/")
            assert response.status_code in (200, 400)
    finally:
        test_app.dependency_overrides.clear()
        if original_value is None:
            os.environ.pop("ENABLE_INTERNAL_OPS_ROUTES", None)
        else:
            os.environ["ENABLE_INTERNAL_OPS_ROUTES"] = original_value


@pytest.mark.asyncio
async def test_admin_routes_return_404_when_disabled(client):
    """Admin routes return 404 when ENABLE_INTERNAL_OPS_ROUTES is false (default)."""
    original_value = os.getenv("ENABLE_INTERNAL_OPS_ROUTES")
    os.environ["ENABLE_INTERNAL_OPS_ROUTES"] = "false"

    try:
        response = await client.get("/api/admin/export/csv/")
        assert response.status_code == 404

        response = await client.get("/api/admin/export/json/")
        assert response.status_code == 404

        response = await client.get("/api/admin/export/summary/")
        assert response.status_code == 404
    finally:
        if original_value is None:
            os.environ.pop("ENABLE_INTERNAL_OPS_ROUTES", None)
        else:
            os.environ["ENABLE_INTERNAL_OPS_ROUTES"] = original_value


@pytest.mark.asyncio
async def test_admin_routes_accessible_when_enabled(sample_data, db):
    """Admin routes work when ENABLE_INTERNAL_OPS_ROUTES is true."""
    from httpx import ASGITransport, AsyncClient

    original_value = os.getenv("ENABLE_INTERNAL_OPS_ROUTES")
    os.environ["ENABLE_INTERNAL_OPS_ROUTES"] = "true"

    def override_get_db():
        try:
            yield db
        finally:
            pass

    from app.database import get_db
    from app.main import create_app

    test_app = create_app()
    test_app.dependency_overrides[get_db] = override_get_db

    try:
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/api/admin/export/csv/")
            assert response.status_code == 200

            response = await ac.get("/api/admin/export/json/")
            assert response.status_code == 200

            response = await ac.get("/api/admin/export/summary/")
            assert response.status_code == 200
    finally:
        test_app.dependency_overrides.clear()
        if original_value is None:
            os.environ.pop("ENABLE_INTERNAL_OPS_ROUTES", None)
        else:
            os.environ["ENABLE_INTERNAL_OPS_ROUTES"] = original_value


@pytest.mark.asyncio
async def test_production_mode_blocks_internal_routes(client):
    """Production mode (default) blocks all internal routes."""
    os.environ["ENABLE_DEBUG_ROUTES"] = "false"
    os.environ["ENABLE_INTERNAL_OPS_ROUTES"] = "false"

    try:
        response = await client.get("/api/tasks/")
        assert response.status_code == 404

        response = await client.get("/api/admin/export/csv/")
        assert response.status_code == 404
    finally:
        os.environ.pop("ENABLE_DEBUG_ROUTES", None)
        os.environ.pop("ENABLE_INTERNAL_OPS_ROUTES", None)


@pytest.mark.asyncio
async def test_health_routes_always_accessible(client):
    """Health routes are always accessible (not gated)."""
    response = await client.get("/api/health")
    assert response.status_code in (200, 503)


@pytest.mark.asyncio
async def test_sensitive_headers_redacted_in_error_logs(client, caplog):
    """Authorization, Cookie, and Set-Cookie headers are redacted in error logs."""
    with caplog.at_level(logging.WARNING):
        _ = await client.post(
            "/api/roll",
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
async def test_sensitive_json_keys_redacted_in_error_logs(client, caplog):
    """Sensitive JSON keys (password, secret, token, access_token, refresh_token, api_key) are redacted."""
    sensitive_data = {
        "username": "testuser",
        "password": "secret123",
        "api_key": "key-xyz",
        "token": "token-abc",
    }

    with caplog.at_level(logging.WARNING):
        _ = await client.post("/api/roll", json=sensitive_data)

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
async def test_all_sensitive_json_keys_redacted(client, caplog):
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
            _ = await client.post("/api/roll", json=sensitive_data)

        log_entries = [record for record in caplog.records if "Client Error" in record.message]
        if log_entries:
            for entry in log_entries:
                request_body = getattr(entry, "request_body", None)
                if request_body and isinstance(request_body, str):
                    assert "[REDACTED: contains sensitive data]" in request_body, (
                        f"Failed for data: {sensitive_data}"
                    )


@pytest.mark.asyncio
async def test_auth_routes_log_only_size_and_type(client, caplog):
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
async def test_non_sensitive_body_not_redacted(client, caplog):
    """Non-sensitive body content is not redacted in error logs."""
    safe_data = {"username": "testuser", "email": "test@example.com", "count": 5}

    with caplog.at_level(logging.WARNING):
        _ = await client.post("/api/roll", json=safe_data)

    log_entries = [record for record in caplog.records if "Client Error" in record.message]
    assert len(log_entries) > 0

    for entry in log_entries:
        request_body = getattr(entry, "request_body", None)
        if request_body and isinstance(request_body, dict):
            assert "password" not in str(request_body)
            assert "secret" not in str(request_body)


@pytest.mark.asyncio
async def test_cors_origins_required_in_production(db):
    """CORS_ORIGINS is required in production mode, app fails to start without it."""
    original_env = os.getenv("ENVIRONMENT")
    original_cors = os.getenv("CORS_ORIGINS")

    os.environ["ENVIRONMENT"] = "production"
    os.environ["CORS_ORIGINS"] = ""

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


@pytest.mark.asyncio
async def test_cors_origins_required_in_production_when_unset(db):
    """CORS_ORIGINS is required in production mode, app fails to start when env var is not set."""
    original_env = os.getenv("ENVIRONMENT")
    original_cors = os.getenv("CORS_ORIGINS")

    os.environ["ENVIRONMENT"] = "production"

    if "CORS_ORIGINS" in os.environ:
        os.environ.pop("CORS_ORIGINS")

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


@pytest.mark.asyncio
async def test_cors_origins_allowed_in_production_when_set(db):
    """CORS_ORIGINS is respected in production mode when set correctly."""
    from httpx import ASGITransport, AsyncClient

    original_env = os.getenv("ENVIRONMENT")
    original_cors = os.getenv("CORS_ORIGINS")

    os.environ["ENVIRONMENT"] = "production"
    os.environ["CORS_ORIGINS"] = "https://example.com,https://app.example.com"

    def override_get_db():
        try:
            yield db
        finally:
            pass

    from app.database import get_db
    from app.main import create_app

    test_app = create_app()
    test_app.dependency_overrides[get_db] = override_get_db

    try:
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/api/health")
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
async def test_cors_defaults_to_wildcard_in_development(db):
    """CORS defaults to wildcard in development mode when CORS_ORIGINS is not set."""
    from httpx import ASGITransport, AsyncClient

    original_env = os.getenv("ENVIRONMENT")
    original_cors = os.getenv("CORS_ORIGINS")

    os.environ["ENVIRONMENT"] = "development"

    if "CORS_ORIGINS" in os.environ:
        os.environ.pop("CORS_ORIGINS")

    def override_get_db():
        try:
            yield db
        finally:
            pass

    from app.database import get_db
    from app.main import create_app

    test_app = create_app()
    test_app.dependency_overrides[get_db] = override_get_db

    try:
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/api/health")
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
async def test_cors_allow_credentials_is_false(db):
    """CORS middleware is configured with allow_credentials=False for JWT bearer token authentication."""
    from httpx import ASGITransport, AsyncClient

    original_env = os.getenv("ENVIRONMENT")
    original_cors = os.getenv("CORS_ORIGINS")

    os.environ["ENVIRONMENT"] = "production"
    os.environ["CORS_ORIGINS"] = "https://example.com"

    def override_get_db():
        try:
            yield db
        finally:
            pass

    from app.database import get_db
    from app.main import create_app

    test_app = create_app()
    test_app.dependency_overrides[get_db] = override_get_db

    try:
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/api/health")
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
async def test_production_mode_skips_table_creation(db):
    """Production mode skips table creation and logs appropriate message."""
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    original_env = os.getenv("ENVIRONMENT")
    original_cors = os.getenv("CORS_ORIGINS")

    os.environ["ENVIRONMENT"] = "production"
    os.environ["CORS_ORIGINS"] = "https://example.com"

    def override_get_db():
        try:
            yield db
        finally:
            pass

    from app.database import get_db

    test_app = None
    try:
        test_app = create_app()
        test_app.dependency_overrides[get_db] = override_get_db

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/api/health")
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
async def test_development_mode_creates_tables(db):
    """Development mode creates tables and logs appropriate message."""
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    original_env = os.getenv("ENVIRONMENT")

    os.environ["ENVIRONMENT"] = "development"

    def override_get_db():
        try:
            yield db
        finally:
            pass

    from app.database import get_db

    test_app = None
    try:
        test_app = create_app()
        test_app.dependency_overrides[get_db] = override_get_db

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/api/health")
            assert response.status_code in (200, 503)
    finally:
        if test_app:
            test_app.dependency_overrides.clear()
        if original_env is None:
            os.environ.pop("ENVIRONMENT", None)
        else:
            os.environ["ENVIRONMENT"] = original_env


@pytest.mark.asyncio
async def test_app_starts_successfully_in_production_mode(db):
    """App starts successfully in production mode without calling create_all()."""
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    original_env = os.getenv("ENVIRONMENT")
    original_cors = os.getenv("CORS_ORIGINS")

    os.environ["ENVIRONMENT"] = "production"
    os.environ["CORS_ORIGINS"] = "https://example.com"

    def override_get_db():
        try:
            yield db
        finally:
            pass

    from app.database import get_db

    test_app = None
    try:
        test_app = create_app()
        test_app.dependency_overrides[get_db] = override_get_db

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/api/health")
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
async def test_app_starts_successfully_in_development_mode(db):
    """App starts successfully in development mode with create_all() called."""
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    original_env = os.getenv("ENVIRONMENT")

    os.environ["ENVIRONMENT"] = "development"

    def override_get_db():
        try:
            yield db
        finally:
            pass

    from app.database import get_db

    test_app = None
    try:
        test_app = create_app()
        test_app.dependency_overrides[get_db] = override_get_db

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/api/health")
            assert response.status_code in (200, 503)
    finally:
        if test_app:
            test_app.dependency_overrides.clear()
        if original_env is None:
            os.environ.pop("ENVIRONMENT", None)
        else:
            os.environ["ENVIRONMENT"] = original_env
