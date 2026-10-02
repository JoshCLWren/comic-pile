"""Configuration default and environment override tests."""

import pytest

from app.config import RecommendationSettings


def test_recommendation_control_mode_env_kill_switch_is_honored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Honor RECOMMENDATION_CONTROL_MODE as the operator kill switch.

    pydantic-settings v2 silently ignores ``json_schema_extra`` env names, so the
    documented operator variable must be wired through ``validation_alias``.
    Without this the legacy control mode could never be reached from the
    environment and contextual selection could not be disabled.

    Args:
        monkeypatch: Pytest fixture used to set recommendation env overrides.

    Returns:
        None.
    """
    monkeypatch.delenv("RECOMMENDATION_CONTROL_MODE", raising=False)
    monkeypatch.delenv("CONTROL_MODE", raising=False)
    monkeypatch.delenv("RECOMMENDATION_ALGORITHM_VERSION", raising=False)
    monkeypatch.delenv("ALGORITHM_VERSION", raising=False)

    assert RecommendationSettings().control_mode == "contextual"

    monkeypatch.setenv("RECOMMENDATION_CONTROL_MODE", "legacy")
    assert RecommendationSettings().control_mode == "legacy"
