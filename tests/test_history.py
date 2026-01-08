"""Tests for history page functionality."""

import pytest


@pytest.mark.asyncio
async def test_history_page_displays_recent_events(client, sample_data):
    """Test that history page displays recent events for each session."""
    response = await client.get("/history")
    assert response.status_code == 200
    html = response.text

    assert "Recent Activity" in html
    assert "Roll" in html
    assert "Rate" in html


@pytest.mark.asyncio
async def test_history_page_shows_full_titles(client, sample_data):
    """Test that history page shows full comic titles without truncation."""
    response = await client.get("/history")
    assert response.status_code == 200
    html = response.text

    assert sample_data["threads"][0].title in html


@pytest.mark.asyncio
async def test_history_page_includes_timestamps(client, sample_data):
    """Test that history page includes timestamps for events."""
    response = await client.get("/history")
    assert response.status_code == 200
    html = response.text

    assert "AM" in html or "PM" in html
