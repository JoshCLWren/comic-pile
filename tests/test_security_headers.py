"""Tests for security headers middleware."""

import os
from unittest.mock import patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_security_headers_present(client: AsyncClient) -> None:
    """Test that security headers are present in responses."""
    response = await client.get("/health")
    assert response.status_code == 200

    headers = response.headers

    # Check Content Security Policy
    assert "Content-Security-Policy" in headers
    csp = headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self' 'unsafe-inline' 'unsafe-eval'" in csp
    assert "style-src 'self' 'unsafe-inline'" in csp
    assert "img-src 'self' data: https:" in csp
    assert "font-src 'self'" in csp
    assert "connect-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "form-action 'self'" in csp
    assert "base-uri 'self'" in csp
    assert "frame-src 'none'" in csp

    # Check HSTS
    assert "Strict-Transport-Security" in headers
    hsts = headers["Strict-Transport-Security"]
    assert "max-age=" in hsts

    # Check X-Content-Type-Options
    assert "X-Content-Type-Options" in headers
    assert headers["X-Content-Type-Options"] == "nosniff"

    # Check X-Frame-Options
    assert "X-Frame-Options" in headers
    assert headers["X-Frame-Options"] == "DENY"

    # Check additional security headers
    assert "X-XSS-Protection" in headers
    assert headers["X-XSS-Protection"] == "1; mode=block"

    assert "Referrer-Policy" in headers
    assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    assert "Permissions-Policy" in headers
    assert "camera=(), microphone=(), geolocation=()" in headers["Permissions-Policy"]


@pytest.mark.asyncio
async def test_security_headers_on_api_endpoint(auth_client: AsyncClient) -> None:
    """Test that security headers are present on API endpoints."""
    response = await auth_client.get("/api/threads/")
    assert response.status_code == 200

    headers = response.headers

    # Check that all security headers are present
    expected_headers = [
        "Content-Security-Policy",
        "Strict-Transport-Security",
        "X-Content-Type-Options",
        "X-Frame-Options",
        "X-XSS-Protection",
        "Referrer-Policy",
        "Permissions-Policy",
    ]

    for header in expected_headers:
        assert header in headers, f"Security header {header} missing from response"


@pytest.mark.asyncio
async def test_hsts_production_environment(client: AsyncClient) -> None:
    """Test that HSTS has production settings in production environment."""
    with patch.dict(os.environ, {"APP_ENV": "production", "ENV": "production"}):
        # Need to create a new app instance to pick up the environment change
        from app.main import create_app
        from httpx import ASGITransport

        test_app = create_app(serve_frontend=False)

        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as test_client:
            response = await test_client.get("/health")
            assert response.status_code == 200

            hsts = response.headers["Strict-Transport-Security"]
            # Production should have long max age, includeSubDomains, and preload
            assert "max-age=63072000" in hsts  # 2 years
            assert "includeSubDomains" in hsts
            assert "preload" in hsts


@pytest.mark.asyncio
async def test_hsts_development_environment(client: AsyncClient) -> None:
    """Test that HSTS has development settings in development environment."""
    with patch.dict(os.environ, {"APP_ENV": "development", "ENV": "development"}):
        # Need to create a new app instance to pick up the environment change
        from app.main import create_app
        from httpx import ASGITransport

        test_app = create_app(serve_frontend=False)

        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as test_client:
            response = await test_client.get("/health")
            assert response.status_code == 200

            hsts = response.headers["Strict-Transport-Security"]
            # Development should have short max age
            assert "max-age=300" in hsts  # 5 minutes


@pytest.mark.asyncio
async def test_security_headers_on_error_response(client: AsyncClient) -> None:
    """Test that security headers are present even on error responses."""
    response = await client.get("/api/nonexistent-endpoint")
    assert response.status_code == 404

    headers = response.headers

    # Security headers should still be present on error responses
    expected_headers = [
        "Content-Security-Policy",
        "Strict-Transport-Security",
        "X-Content-Type-Options",
        "X-Frame-Options",
        "X-XSS-Protection",
        "Referrer-Policy",
        "Permissions-Policy",
    ]

    for header in expected_headers:
        assert header in headers, f"Security header {header} missing from error response"


@pytest.mark.asyncio
async def test_csp_prevents_xss(client: AsyncClient) -> None:
    """Test that CSP header is properly configured to prevent XSS."""
    response = await client.get("/health")
    assert response.status_code == 200

    csp = response.headers["Content-Security-Policy"]

    # CSP should be restrictive and prevent common XSS vectors
    csp_directives = [directive.strip() for directive in csp.split(";")]
    csp_dict = {}

    for directive in csp_directives:
        if directive:
            parts = directive.split(" ", 1)
            if len(parts) == 2:
                key, values = parts
                csp_dict[key] = values

    # Check key security restrictions
    assert "default-src" in csp_dict
    assert "'self'" in csp_dict["default-src"]

    assert "script-src" in csp_dict
    script_src = csp_dict["script-src"]
    # Allow inline scripts and eval for app functionality but restrict external scripts
    assert "'unsafe-inline'" in script_src
    assert "'unsafe-eval'" in script_src
    assert "'self'" in script_src

    assert "frame-ancestors" in csp_dict
    assert csp_dict["frame-ancestors"] == "'none'"  # Prevent framing

    assert "frame-src" in csp_dict
    assert csp_dict["frame-src"] == "'none'"  # Prevent iframes

    assert "form-action" in csp_dict
    assert csp_dict["form-action"] == "'self'"  # Restrict form submissions to same origin
