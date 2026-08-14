import os
from fastapi.testclient import TestClient

# Must set environment variable BEFORE importing app to ensure
# that the conditional router inclusion in create_app() is triggered.
os.environ["TEST_ENVIRONMENT"] = "true"
from app.main import create_app
from app.startup_diagnostics import reset_startup_diagnostics_for_test

app = create_app()
reset_startup_diagnostics_for_test()
client = TestClient(app)

def test_response_time_header():
    # First request should have cold start true
    response = client.get("/health")
    assert response.status_code == 200
    assert "X-Response-Time" in response.headers
    assert response.headers.get("X-Server-Cold-Start") == "true"
    # Second request should have cold start false
    response2 = client.get("/health")
    assert response2.headers.get("X-Server-Cold-Start") == "false"

def test_metrics_endpoint():
    response = client.get("/api/metrics")
    assert response.status_code == 200
    data = response.json()
    assert "startup_time" in data
    assert "startup_duration" in data
    assert isinstance(data["startup_time"], float)
    assert isinstance(data["startup_duration"], float) or data["startup_duration"] is None
