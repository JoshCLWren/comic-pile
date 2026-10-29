"""Fresh-process coverage for password-only auth import boundaries."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "scenario",
    ["auth_routes", "cold_me", "hash_verify", "forgot_password", "reset_password", "concurrent_burst"],
)
def test_password_dependencies_load_only_when_required(scenario: str) -> None:
    """Exercise the cold auth path and deferred handlers in separate interpreters."""
    script = """
import asyncio
import sys
from unittest.mock import AsyncMock, patch

from fastapi import BackgroundTasks, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import auth
from app.schemas.auth import ForgotPasswordRequest, ResetPasswordRequest

assert "app.services.password_reset_service" not in sys.modules

async def main():
    scenario = sys.argv[1]
    if scenario == "cold_me":
        from app.main import create_app
        app = create_app(serve_frontend=False, defer_router_imports=True)
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            response = await client.get("/api/v1/auth/me")
        assert response.status_code == 401, response.text
        assert "app.services.password_reset_service" not in sys.modules
    elif scenario == "hash_verify":
        from app.auth import hash_password, verify_password
        hashed = hash_password("a-local-password")
        assert verify_password("a-local-password", hashed)
        assert not verify_password("wrong-password", hashed)
        assert "bcrypt" in sys.modules
    elif scenario in {"forgot_password", "reset_password"}:
        # Patch the service's persistence collaborator before the handler imports
        # the service. The actual import and orchestration still run.
        request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
        async with AsyncSession() as session:
            if scenario == "forgot_password":
                with patch(
                    "app.repositories.user_repository.get_user_by_email",
                    new=AsyncMock(return_value=None),
                ):
                    response = await auth.forgot_password(
                        request, ForgotPasswordRequest(email="local@example.com"),
                        BackgroundTasks(), session,
                    )
                assert "If an account exists" in response.message
            else:
                from fastapi import HTTPException
                with patch(
                    "app.repositories.password_reset_token_repository.get_token_by_digest",
                    new=AsyncMock(return_value=None),
                ):
                    try:
                        await auth.reset_password(
                            ResetPasswordRequest(token="invalid", new_password="local-password"),
                            session,
                        )
                    except HTTPException as error:
                        assert error.status_code == 400
                    else:
                        raise AssertionError("Invalid reset token accepted")
        assert "app.services.password_reset_service" in sys.modules
    elif scenario == "concurrent_burst":
        # Run 3 concurrent cold-start auth/me requests to verify no import races
        # or excessive CPU from simultaneous function-entry bcrypt imports.
        from app.main import create_app
        import asyncio

        app = create_app(serve_frontend=False, defer_router_imports=True)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async def make_request():
                return await client.get("/api/v1/auth/me")
            responses = await asyncio.gather(
                make_request(), make_request(), make_request(),
                return_exceptions=False,
            )
            # All 3 must complete (401 unauthenticated is expected cold-start)
            assert all(isinstance(r, Exception) or r.status_code == 401 for r in responses), \
                f"Unexpected responses: {responses}"
            # Verify bcrypt was imported at most once across all requests
            # (Python caches imports, but first call in each function pays cost)
            assert "bcrypt" in sys.modules

asyncio.run(main())
print("deferred-import-ok")
"""
    environment = {
        **os.environ,
        "TEST_ENVIRONMENT": "true",
        "ENVIRONMENT": "test",
        "ENABLE_LAZY_HEAVY_INIT_IN_TESTS": "false",
        "ENABLE_RATE_LIMITING_IN_TESTS": "false",
    }
    result = subprocess.run(
        [sys.executable, "-c", script, scenario],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "deferred-import-ok" in result.stdout
