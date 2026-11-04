"""Regression tests for session-mode bandwidth source serialization."""

import pytest

from app.schemas.session import SessionMode


@pytest.mark.parametrize("source", ["snooze", "quiz"])
def test_session_mode_accepts_persisted_bandwidth_sources(source: str) -> None:
    """Bootstrap must serialize every valid persisted bandwidth source."""
    session_mode = SessionMode(bandwidth_source=source)

    assert session_mode.bandwidth_source == source
