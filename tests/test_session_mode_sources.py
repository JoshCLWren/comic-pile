"""Regression tests for session-mode bandwidth source serialization."""

import pytest

from app.schemas.roll import SessionModeResponse
from app.schemas.session import SessionMode


@pytest.mark.parametrize("source", ["snooze", "quiz"])
def test_session_mode_accepts_persisted_bandwidth_sources(source: str) -> None:
    """Bootstrap must serialize every valid persisted bandwidth source."""
    session_mode = SessionMode(bandwidth_source=source)

    assert session_mode.bandwidth_source == source


@pytest.mark.parametrize("source", ["snooze", "quiz"])
def test_session_mode_response_accepts_persisted_bandwidth_sources(source: str) -> None:
    """Session-mode updates must serialize every valid persisted bandwidth source."""
    response = SessionModeResponse(
        active_bandwidth="balanced",
        predicted_bandwidth="balanced",
        bandwidth_source=source,
        active_intent="balanced",
        predicted_intent="balanced",
    )

    assert response.bandwidth_source == source
