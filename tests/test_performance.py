"""Tests for performance telemetry middleware and metrics endpoint."""
import os
from fastapi.testclient import TestClient

from app.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token
from app.startup_diagnostics import reset_startup_diagnostics_for_test
import app.startup_diagnostics as startup_diagnostics

# Must set environment variable BEFORE importing app to ensure
# that the conditional router inclusion in create_app() is triggered.
os.environ["TEST_ENVIRONMENT"] = "true"
from app.main import create_app

app = create_app()
print(f"Before reset: request_count={startup_diagnostics._request_count}")
reset_startup_diagnostics_for_test()
print(f"After reset: request_count={startup_diagnostics._request_count}")
client = TestClient(app)

def test_response_time_header():
    """Verify X-Response-Time and X-Server-Cold-Start headers are set."""
    print(f"Before first request: request_count={startup_diagnostics._request_count}")
    # First request should have cold start true
    response = client.get("/health")
    print(f"After first request: request_count={startup_diagnostics._request_count}")
    assert response.status_code == 200
    assert "X-Response-Time" in response.headers
    print(f"First request X-Server-Cold-Start: {response.headers.get('X-Server-Cold-Start')}")
    assert response.headers.get("X-Server-Cold-Start") == "true"
    # Second request should have cold start false
    response2 = client.get("/health")
    print(f"After second request: request_count={startup_diagnostics._request_count}")
    assert response2.headers.get("X-Server-Cold-Start") == "false"

def test_metrics_endpoint():
    """Verify the /api/metrics endpoint returns startup_time and startup_duration."""
    response = client.get("/api/metrics")
    assert response.status_code == 200
    data = response.json()
    assert "startup_time" in data
    assert "startup_duration" in data
    assert isinstance(data["startup_time"], float)
    assert isinstance(data["startup_duration"], float) or data["startup_duration"] is None

def test_csrf_protection():
    """Verify the CSRF middleware rejects authenticated POSTs without a token.

    The CSRF check only applies to requests that carry an ``Authorization``
    header; unauthenticated requests fall through to normal auth handling.
    """
    # With an Authorization header but no CSRF token, the CSRF middleware must
    # reject the mutating request and report the CSRF-specific detail.
    client.headers["Authorization"] = "Bearer test"
    response = client.post("/api/roll", json={})
    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF token missing or invalid"}

    # With a valid CSRF token attached, the request passes the CSRF layer even
    # though the (invalid) bearer token still fails downstream auth.
    token = generate_csrf_token()
    client.cookies.set(CSRF_COOKIE_NAME, token)
    client.headers[CSRF_HEADER_NAME] = token
    response2 = client.post("/api/roll", json={})
    assert response2.json().get("detail") != "CSRF token missing or invalid"
