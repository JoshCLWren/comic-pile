"""Focused backend test for #2757 bounded demo adapter."""

import pytest
from fastapi.testclient import TestClient


def test_demo_roll_deterministic_and_ephemeral():
    from app.main import app
    client = TestClient(app)
    response = client.get("/api/demo/roll")
    assert response.status_code == 200
    payload = response.json()
    assert payload["thread_id"] == 999
    assert "Demo" in payload["title"]
    assert payload["explanation"] is not None


def test_demo_bootstrap_ephemeral_metadata():
    from app.main import app
    client = TestClient(app)
    response = client.get("/api/demo/bootstrap")
    assert response.status_code == 200
    payload = response.json()
    assert payload["metadata"]["demo"] is True
    assert payload["metadata"]["persistent"] is False
