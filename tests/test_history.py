"""Tests for history page functionality."""

import pytest


@pytest.mark.asyncio
async def test_sessions_list_returns_data(auth_client, sample_data):
    """Test that sessions API returns session data for history page."""
    _ = sample_data
    response = await auth_client.get("/api/sessions/")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
