"""Tests for rate API endpoints."""

from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from sqlalchemy import select

from app.models import Event, Issue, Thread
from comic_pile.queue import QueuePositionChanges, get_bounded_roll_pool_rows
from httpx import AsyncClient
from app.models import ReadingSession
from sqlalchemy.ext.asyncio import AsyncSession


def test_rating_settings_returns_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test rating settings return default values."""
    from app.config import clear_settings_cache, get_rating_settings

    # Clear any cached settings and env vars
    for var in ["RATING_MIN", "RATING_MAX", "RATING_THRESHOLD"]:
        monkeypatch.delenv(var, raising=False)
    clear_settings_cache()

    settings = get_rating_settings()
    assert settings.rating_min == 0.5
    assert settings.rating_max == 5.0
    assert settings.rating_threshold == 4.0


def test_rating_settings_returns_custom_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test rating settings return custom values when set."""
    from app.config import clear_settings_cache, get_rating_settings

    monkeypatch.setenv("RATING_MIN", "1.0")
    monkeypatch.setenv("RATING_MAX", "4.5")
    monkeypatch.setenv("RATING_THRESHOLD", "3.5")
    clear_settings_cache()

    settings = get_rating_settings()
    assert settings.rating_min == 1.0
    assert settings.rating_max == 4.5
    assert settings.rating_threshold == 3.5


def test_rating_settings_validates_range(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test rating settings validate and raise ValueError for out-of-range values."""
    from pydantic import ValidationError

    from app.config import RatingSettings, clear_settings_cache

    # Values outside range raise ValidationError
    monkeypatch.setenv("RATING_MIN", "10.0")
    clear_settings_cache()
    with pytest.raises(ValidationError) as exc_info:
        RatingSettings()
    assert "RATING_MIN" in str(exc_info.value)

    monkeypatch.setenv("RATING_MAX", "15.0")
    clear_settings_cache()
    with pytest.raises(ValidationError) as exc_info:
        RatingSettings()
    assert "RATING_MAX" in str(exc_info.value)

    monkeypatch.setenv("RATING_THRESHOLD", "-1.0")
    clear_settings_cache()
    with pytest.raises(ValidationError) as exc_info:
        RatingSettings()
    assert "RATING_THRESHOLD" in str(exc_info.value)
