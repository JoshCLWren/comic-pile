"""Tests for configuration validation (issue #296).

These tests verify that invalid environment variable values raise validation errors
instead of silently falling back to defaults.
"""

from collections.abc import Generator

import pytest
from pydantic import ValidationError

from app.config import (
    SessionSettings,
    RatingSettings,
    clear_settings_cache,
)


@pytest.fixture(autouse=True)
def clear_cache() -> Generator:
    """Clear settings cache before each test."""
    clear_settings_cache()
    yield
    clear_settings_cache()


class TestSessionSettingsValidation:
    """Test SessionSettings validation."""

    def test_valid_session_gap_hours(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that valid session_gap_hours values are accepted."""
        monkeypatch.setenv("SESSION_GAP_HOURS", "12")
        clear_settings_cache()
        settings = SessionSettings()
        assert settings.session_gap_hours == 12

    def test_session_gap_hours_minimum_boundary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that session_gap_hours=1 (minimum) is accepted."""
        monkeypatch.setenv("SESSION_GAP_HOURS", "1")
        clear_settings_cache()
        settings = SessionSettings()
        assert settings.session_gap_hours == 1

    def test_session_gap_hours_maximum_boundary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that session_gap_hours=168 (maximum) is accepted."""
        monkeypatch.setenv("SESSION_GAP_HOURS", "168")
        clear_settings_cache()
        settings = SessionSettings()
        assert settings.session_gap_hours == 168

    def test_invalid_session_gap_hours_too_low(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that session_gap_hours < 1 raises ValidationError."""
        monkeypatch.setenv("SESSION_GAP_HOURS", "0")
        clear_settings_cache()
        with pytest.raises(ValidationError) as exc_info:
            SessionSettings()
        assert "session_gap_hours" in str(exc_info.value).lower()

    def test_invalid_session_gap_hours_too_high(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that session_gap_hours > 168 raises ValidationError."""
        monkeypatch.setenv("SESSION_GAP_HOURS", "169")
        clear_settings_cache()
        with pytest.raises(ValidationError) as exc_info:
            SessionSettings()
        assert "session_gap_hours" in str(exc_info.value).lower()

    def test_invalid_session_gap_hours_negative(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that negative session_gap_hours raises ValidationError."""
        monkeypatch.setenv("SESSION_GAP_HOURS", "-5")
        clear_settings_cache()
        with pytest.raises(ValidationError) as exc_info:
            SessionSettings()
        assert "session_gap_hours" in str(exc_info.value).lower()

    def test_valid_start_die(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that valid start_die values are accepted."""
        monkeypatch.setenv("START_DIE", "10")
        clear_settings_cache()
        settings = SessionSettings()
        assert settings.start_die == 10

    def test_start_die_minimum_boundary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that start_die=4 (minimum) is accepted."""
        monkeypatch.setenv("START_DIE", "4")
        clear_settings_cache()
        settings = SessionSettings()
        assert settings.start_die == 4

    def test_start_die_maximum_boundary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that start_die=20 (maximum) is accepted."""
        monkeypatch.setenv("START_DIE", "20")
        clear_settings_cache()
        settings = SessionSettings()
        assert settings.start_die == 20

    def test_invalid_start_die_too_low(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that start_die < 4 raises ValidationError."""
        monkeypatch.setenv("START_DIE", "3")
        clear_settings_cache()
        with pytest.raises(ValidationError) as exc_info:
            SessionSettings()
        assert "start_die" in str(exc_info.value).lower()

    def test_invalid_start_die_too_high(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that start_die > 20 raises ValidationError."""
        monkeypatch.setenv("START_DIE", "21")
        clear_settings_cache()
        with pytest.raises(ValidationError) as exc_info:
            SessionSettings()
        assert "start_die" in str(exc_info.value).lower()

    def test_invalid_start_die_example_from_issue(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test the example from issue #296: START_DIE=100 should fail."""
        monkeypatch.setenv("START_DIE", "100")
        clear_settings_cache()
        with pytest.raises(ValidationError) as exc_info:
            SessionSettings()
        assert "start_die" in str(exc_info.value).lower()


class TestRatingSettingsValidation:
    """Test RatingSettings validation."""

    def test_valid_rating_min(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that valid rating_min values are accepted."""
        monkeypatch.setenv("RATING_MIN", "1.0")
        clear_settings_cache()
        settings = RatingSettings()
        assert settings.rating_min == 1.0

    def test_rating_min_minimum_boundary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that rating_min=0.0 (minimum) is accepted."""
        monkeypatch.setenv("RATING_MIN", "0.0")
        clear_settings_cache()
        settings = RatingSettings()
        assert settings.rating_min == 0.0

    def test_rating_min_maximum_boundary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that rating_min=5.0 (maximum) is accepted."""
        monkeypatch.setenv("RATING_MIN", "5.0")
        clear_settings_cache()
        settings = RatingSettings()
        assert settings.rating_min == 5.0

    def test_invalid_rating_min_too_low(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that rating_min < 0.0 raises ValidationError."""
        monkeypatch.setenv("RATING_MIN", "-0.1")
        clear_settings_cache()
        with pytest.raises(ValidationError) as exc_info:
            RatingSettings()
        assert "rating_min" in str(exc_info.value).lower()

    def test_invalid_rating_min_too_high(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that rating_min > 5.0 raises ValidationError."""
        monkeypatch.setenv("RATING_MIN", "5.1")
        clear_settings_cache()
        with pytest.raises(ValidationError) as exc_info:
            RatingSettings()
        assert "rating_min" in str(exc_info.value).lower()

    def test_valid_rating_max(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that valid rating_max values are accepted."""
        monkeypatch.setenv("RATING_MAX", "4.5")
        clear_settings_cache()
        settings = RatingSettings()
        assert settings.rating_max == 4.5

    def test_rating_max_minimum_boundary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that rating_max=0.5 (minimum) is accepted."""
        monkeypatch.setenv("RATING_MAX", "0.5")
        clear_settings_cache()
        settings = RatingSettings()
        assert settings.rating_max == 0.5

    def test_rating_max_maximum_boundary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that rating_max=5.0 (maximum) is accepted."""
        monkeypatch.setenv("RATING_MAX", "5.0")
        clear_settings_cache()
        settings = RatingSettings()
        assert settings.rating_max == 5.0

    def test_invalid_rating_max_too_low(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that rating_max < 0.5 raises ValidationError."""
        monkeypatch.setenv("RATING_MAX", "0.4")
        clear_settings_cache()
        with pytest.raises(ValidationError) as exc_info:
            RatingSettings()
        assert "rating_max" in str(exc_info.value).lower()

    def test_invalid_rating_max_too_high(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that rating_max > 5.0 raises ValidationError."""
        monkeypatch.setenv("RATING_MAX", "5.1")
        clear_settings_cache()
        with pytest.raises(ValidationError) as exc_info:
            RatingSettings()
        assert "rating_max" in str(exc_info.value).lower()

    def test_valid_rating_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that valid rating_threshold values are accepted."""
        monkeypatch.setenv("RATING_THRESHOLD", "4.5")
        clear_settings_cache()
        settings = RatingSettings()
        assert settings.rating_threshold == 4.5

    def test_rating_threshold_minimum_boundary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that rating_threshold=0.5 (minimum) is accepted."""
        monkeypatch.setenv("RATING_THRESHOLD", "0.5")
        clear_settings_cache()
        settings = RatingSettings()
        assert settings.rating_threshold == 0.5

    def test_rating_threshold_maximum_boundary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that rating_threshold=5.0 (maximum) is accepted."""
        monkeypatch.setenv("RATING_THRESHOLD", "5.0")
        clear_settings_cache()
        settings = RatingSettings()
        assert settings.rating_threshold == 5.0

    def test_invalid_rating_threshold_too_low(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that rating_threshold < 0.5 raises ValidationError."""
        monkeypatch.setenv("RATING_THRESHOLD", "0.4")
        clear_settings_cache()
        with pytest.raises(ValidationError) as exc_info:
            RatingSettings()
        assert "rating_threshold" in str(exc_info.value).lower()

    def test_invalid_rating_threshold_too_high(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that rating_threshold > 5.0 raises ValidationError."""
        monkeypatch.setenv("RATING_THRESHOLD", "5.1")
        clear_settings_cache()
        with pytest.raises(ValidationError) as exc_info:
            RatingSettings()
        assert "rating_threshold" in str(exc_info.value).lower()
