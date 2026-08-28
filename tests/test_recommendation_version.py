"""Tests for recommendation algorithm versioning and safe legacy rollback (#1767).

These tests verify the canonical algorithm version identifier, the operator
kill switch for legacy unweighted selection, and that version/control state
are correctly reported for decision snapshots.
"""

from __future__ import annotations

import os
from unittest.mock import patch

from app.config import clear_settings_cache, get_recommendation_settings
from app.recommendation_version import (
    ALGORITHM_CONTROL_STATE_LEGACY_UNWEIGHTED,
    ALGORITHM_CONTROL_STATE_WEIGHTED,
    CANONICAL_ALGORITHM_VERSION,
    LEGACY_ALGORITHM_VERSION,
    get_current_algorithm_version,
    get_current_control_state,
    is_legacy_mode_enabled,
)


class TestCanonicalConstants:
    """Verify the canonical version and control-state constants."""

    def test_canonical_algorithm_version_is_v1_contextual(self) -> None:
        """CANONICAL_ALGORITHM_VERSION constant is v1-contextual."""
        assert CANONICAL_ALGORITHM_VERSION == "v1-contextual"

    def test_legacy_algorithm_version_is_legacy(self) -> None:
        """LEGACY_ALGORITHM_VERSION constant is legacy."""
        assert LEGACY_ALGORITHM_VERSION == "legacy"

    def test_control_state_weighted_is_contextual(self) -> None:
        """ALGORITHM_CONTROL_STATE_WEIGHTED constant is contextual."""
        assert ALGORITHM_CONTROL_STATE_WEIGHTED == "contextual"

    def test_control_state_legacy_unweighted_is_legacy(self) -> None:
        """ALGORITHM_CONTROL_STATE_LEGACY_UNWEIGHTED constant is legacy."""
        assert ALGORITHM_CONTROL_STATE_LEGACY_UNWEIGHTED == "legacy"


class TestLegacyModeEnabled:
    """Tests for the is_legacy_mode_enabled kill switch."""

    def setup_method(self) -> None:
        """Clear settings cache before each test."""
        clear_settings_cache()

    def teardown_method(self) -> None:
        """Clear settings cache after each test."""
        clear_settings_cache()

    def test_defaults_to_contextual_false(self) -> None:
        """Default control_mode is 'contextual', so legacy mode is disabled."""
        assert is_legacy_mode_enabled() is False

    def test_explicit_contextual_mode_disables_legacy(self) -> None:
        """Explicit 'contextual' control_mode keeps legacy mode disabled."""
        with patch.dict(os.environ, {"RECOMMENDATION_CONTROL_MODE": "contextual"}):
            clear_settings_cache()
            assert is_legacy_mode_enabled() is False

    def test_legacy_mode_enables_legacy(self) -> None:
        """Setting control_mode='legacy' enables the kill switch."""
        with patch.dict(os.environ, {"RECOMMENDATION_CONTROL_MODE": "legacy"}):
            clear_settings_cache()
            assert is_legacy_mode_enabled() is True

    def test_case_sensitivity(self) -> None:
        """Control mode values are case-sensitive literals."""
        with patch.dict(os.environ, {"RECOMMENDATION_CONTROL_MODE": "Legacy"}):
            clear_settings_cache()
            # "Legacy" != "legacy" so should default to contextual
            assert is_legacy_mode_enabled() is False

    def test_invalid_mode_defaults_to_contextual(self) -> None:
        """Invalid control_mode values fall back to contextual (disabled)."""
        with patch.dict(os.environ, {"RECOMMENDATION_CONTROL_MODE": "invalid"}):
            clear_settings_cache()
            # Pydantic Literal validation should reject, but if it passes,
            # the equality check will fail and return False
            assert is_legacy_mode_enabled() is False


class TestCurrentAlgorithmVersion:
    """Tests for get_current_algorithm_version()."""

    def setup_method(self) -> None:
        """Clear settings cache before each test."""
        clear_settings_cache()

    def teardown_method(self) -> None:
        """Clear settings cache after each test."""
        clear_settings_cache()

    def test_returns_canonical_when_contextual(self) -> None:
        """Returns CANONICAL_ALGORITHM_VERSION when legacy mode is off."""
        with patch.dict(os.environ, {"RECOMMENDATION_CONTROL_MODE": "contextual"}):
            clear_settings_cache()
            assert get_current_algorithm_version() == CANONICAL_ALGORITHM_VERSION

    def test_returns_legacy_when_legacy_mode(self) -> None:
        """Returns LEGACY_ALGORITHM_VERSION when legacy mode is on."""
        with patch.dict(os.environ, {"RECOMMENDATION_CONTROL_MODE": "legacy"}):
            clear_settings_cache()
            assert get_current_algorithm_version() == LEGACY_ALGORITHM_VERSION


class TestCurrentControlState:
    """Tests for get_current_control_state()."""

    def setup_method(self) -> None:
        """Clear settings cache before each test."""
        clear_settings_cache()

    def teardown_method(self) -> None:
        """Clear settings cache after each test."""
        clear_settings_cache()

    def test_returns_weighted_when_contextual(self) -> None:
        """Returns ALGORITHM_CONTROL_STATE_WEIGHTED when legacy mode is off."""
        with patch.dict(os.environ, {"RECOMMENDATION_CONTROL_MODE": "contextual"}):
            clear_settings_cache()
            assert get_current_control_state() == ALGORITHM_CONTROL_STATE_WEIGHTED

    def test_returns_legacy_unweighted_when_legacy(self) -> None:
        """Returns ALGORITHM_CONTROL_STATE_LEGACY_UNWEIGHTED when legacy mode is on."""
        with patch.dict(os.environ, {"RECOMMENDATION_CONTROL_MODE": "legacy"}):
            clear_settings_cache()
            assert get_current_control_state() == ALGORITHM_CONTROL_STATE_LEGACY_UNWEIGHTED


class TestTransitionBehavior:
    """Tests for toggling between contextual and legacy modes."""

    def setup_method(self) -> None:
        """Clear settings cache before each test."""
        clear_settings_cache()

    def teardown_method(self) -> None:
        """Clear settings cache after each test."""
        clear_settings_cache()

    def test_toggle_contextual_to_legacy_changes_version(self) -> None:
        """Switching from contextual to legacy changes reported version."""
        with patch.dict(os.environ, {"RECOMMENDATION_CONTROL_MODE": "contextual"}):
            clear_settings_cache()
            assert get_current_algorithm_version() == CANONICAL_ALGORITHM_VERSION
            assert get_current_control_state() == ALGORITHM_CONTROL_STATE_WEIGHTED

        with patch.dict(os.environ, {"RECOMMENDATION_CONTROL_MODE": "legacy"}):
            clear_settings_cache()
            assert get_current_algorithm_version() == LEGACY_ALGORITHM_VERSION
            assert get_current_control_state() == ALGORITHM_CONTROL_STATE_LEGACY_UNWEIGHTED

    def test_toggle_legacy_to_contextual_restores_version(self) -> None:
        """Switching back from legacy to contextual restores canonical version."""
        with patch.dict(os.environ, {"RECOMMENDATION_CONTROL_MODE": "legacy"}):
            clear_settings_cache()
            assert get_current_algorithm_version() == LEGACY_ALGORITHM_VERSION

        with patch.dict(os.environ, {"RECOMMENDATION_CONTROL_MODE": "contextual"}):
            clear_settings_cache()
            assert get_current_algorithm_version() == CANONICAL_ALGORITHM_VERSION
            assert get_current_control_state() == ALGORITHM_CONTROL_STATE_WEIGHTED

    def test_settings_cache_clearing_required_for_transition(self) -> None:
        """Settings are cached; cache must be cleared for mode changes to take effect."""
        with patch.dict(os.environ, {"RECOMMENDATION_CONTROL_MODE": "contextual"}):
            clear_settings_cache()
            assert get_current_algorithm_version() == CANONICAL_ALGORITHM_VERSION

            # Change env but don't clear cache - should still return cached value
            os.environ["RECOMMENDATION_CONTROL_MODE"] = "legacy"
            assert get_current_algorithm_version() == CANONICAL_ALGORITHM_VERSION

            # Clear cache - now should reflect new value
            clear_settings_cache()
            assert get_current_algorithm_version() == LEGACY_ALGORITHM_VERSION


class TestRecommendationSettingsIntegration:
    """Integration tests with the RecommendationSettings config class."""

    def setup_method(self) -> None:
        """Clear settings cache before each test."""
        clear_settings_cache()

    def teardown_method(self) -> None:
        """Clear settings cache after each test."""
        clear_settings_cache()

    def test_algorithm_version_setting_default(self) -> None:
        """RecommendationSettings.algorithm_version defaults to v1-contextual."""
        settings = get_recommendation_settings()
        assert settings.algorithm_version == "v1-contextual"

    def test_control_mode_setting_default(self) -> None:
        """RecommendationSettings.control_mode defaults to contextual."""
        settings = get_recommendation_settings()
        assert settings.control_mode == "contextual"

    def test_env_override_algorithm_version(self) -> None:
        """RECOMMENDATION_ALGORITHM_VERSION env var overrides algorithm_version."""
        with patch.dict(os.environ, {"RECOMMENDATION_ALGORITHM_VERSION": "v2-experimental"}):
            clear_settings_cache()
            settings = get_recommendation_settings()
            assert settings.algorithm_version == "v2-experimental"

    def test_env_override_control_mode(self) -> None:
        """RECOMMENDATION_CONTROL_MODE env var overrides control_mode."""
        with patch.dict(os.environ, {"RECOMMENDATION_CONTROL_MODE": "legacy"}):
            clear_settings_cache()
            settings = get_recommendation_settings()
            assert settings.control_mode == "legacy"
