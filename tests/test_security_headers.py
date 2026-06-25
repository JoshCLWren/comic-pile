"""Tests for security headers middleware."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_security_headers_present(client: AsyncClient) -> None:
    """Test that security headers are present in responses."""
    response = await client.get("/health")
    assert response.status_code == 200

    headers = response.headers

    assert "Content-Security-Policy" in headers
    csp = headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp

    assert "Strict-Transport-Security" in headers
    assert "max-age=" in headers["Strict-Transport-Security"]

    assert "X-Content-Type-Options" in headers
    assert headers["X-Content-Type-Options"] == "nosniff"

    assert "X-Frame-Options" in headers
    assert headers["X-Frame-Options"] == "DENY"

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
        assert header in response.headers, f"Security header {header} missing from response"


@pytest.mark.asyncio
async def test_csp_restrictive(client: AsyncClient) -> None:
    """Test that CSP header is properly configured to prevent XSS."""
    response = await client.get("/health")
    assert response.status_code == 200

    csp = response.headers["Content-Security-Policy"]

    csp_directives = [directive.strip() for directive in csp.split(";")]
    csp_dict = {}

    for directive in csp_directives:
        if directive:
            parts = directive.split(" ", 1)
            if len(parts) == 2:
                key, values = parts
                csp_dict[key] = values

    assert "default-src" in csp_dict
    assert "'self'" in csp_dict["default-src"]
    assert "frame-ancestors" in csp_dict
    assert csp_dict["frame-ancestors"] == "'none'"
    assert "frame-src" in csp_dict
    assert csp_dict["frame-src"] == "'none'"
    assert "form-action" in csp_dict
    assert csp_dict["form-action"] == "'self'"
