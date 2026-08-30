"""Tests for the executable production cache provider decision (issue #1785).

The go/no-go memo in ``docs/CACHE_PROVIDER_DECISION_2026-08.md`` chooses the
production provider and records the numbers behind it. These tests pin the memo's
conclusion to the runtime configuration and keep the latency rule and the
monthly-demand projection reproducible without production access.
"""

from __future__ import annotations

import pytest

from app.cache_metrics import (
    CONSERVATIVE_MONTHLY_COMMAND_BUDGET,
    MONTHLY_HEADROOM_COMMANDS,
    UPSTASH_FREE_MONTHLY_COMMANDS,
)
from app.cache_provider_decision import (
    PRODUCTION_CACHE_PROVIDER,
    CacheCommandProjection,
    LatencySample,
    project_monthly_cache_commands,
    provider_recommendation,
)
from app.config import RedisSettings


def redis_settings(**values: bool | str | None) -> RedisSettings:
    """Build isolated Redis settings without reading ambient Redis credentials."""
    isolated_values: dict[str, bool | str | None] = {
        "cache_provider": "postgres",
        "cache_enabled": False,
        "upstash_redis_rest_url": None,
        "upstash_redis_rest_token": None,
        "redis_url": None,
    }
    isolated_values.update(values or {})
    return RedisSettings.model_validate(isolated_values)


class TestMemoConclusionAndProductionConfig:
    """The memo's conclusion must match the runtime default configuration."""

    def test_memo_conclusion_chooses_postgres(self) -> None:
        """The provider-decision memo concludes with the Postgres provider."""
        assert PRODUCTION_CACHE_PROVIDER == "postgres"

    def test_runtime_default_resolution_matches_memo_conclusion(self) -> None:
        """Production defaults resolve to the memo's chosen provider."""
        settings = redis_settings()

        assert settings.cache_provider == PRODUCTION_CACHE_PROVIDER
        assert settings.effective_provider == PRODUCTION_CACHE_PROVIDER
        assert settings.is_configured is True

    def test_redis_requires_explicit_enablement_to_override_postgres(self) -> None:
        """Redis only becomes the effective provider with an explicit opt-in."""
        settings = redis_settings(
            cache_provider="redis",
            cache_enabled=False,
            upstash_redis_rest_url="https://example.upstash.io",
            upstash_redis_rest_token="test-token",
        )

        assert settings.effective_provider == "off"


class TestLatencyDecisionRule:
    """The latency decision rule mirrors docs/CACHE_LOOKUP_LATENCY_2026-08.md."""

    def test_upstash_meaningfully_faster_below_two_x(self) -> None:
        """Upstash under 2x the Neon p50 is meaningfully faster."""
        upstash = LatencySample(p50_ms=8.0, p95_ms=10.0)
        neon = LatencySample(p50_ms=5.0, p95_ms=6.0)

        assert provider_recommendation(upstash, neon) == "upstash"

    def test_postgres_preferred_at_exactly_two_x(self) -> None:
        """A 2.0x ratio is not 'meaningfully faster' for Upstash."""
        upstash = LatencySample(p50_ms=10.0, p95_ms=12.0)
        neon = LatencySample(p50_ms=5.0, p95_ms=6.0)

        assert provider_recommendation(upstash, neon) == "postgres"

    def test_postgres_preferred_when_upstash_at_least_two_x(self) -> None:
        """At or above 2x, Neon point reads are not meaningfully slower."""
        upstash = LatencySample(p50_ms=12.0, p95_ms=14.0)
        neon = LatencySample(p50_ms=5.0, p95_ms=6.0)

        assert provider_recommendation(upstash, neon) == "postgres"

    def test_postgres_preferred_when_neon_already_under_three_ms(self) -> None:
        """A sub-3 ms Neon absolute makes Upstash not meaningfully better."""
        upstash = LatencySample(p50_ms=2.0, p95_ms=3.0)
        neon = LatencySample(p50_ms=2.0, p95_ms=3.0)

        assert provider_recommendation(upstash, neon) == "postgres"

    def test_investigate_when_upstash_variance_is_high(self) -> None:
        """A p95/p50 ratio above 5x on the Upstash path blocks a decision."""
        upstash = LatencySample(p50_ms=10.0, p95_ms=90.0)
        neon = LatencySample(p50_ms=5.0, p95_ms=6.0)

        assert provider_recommendation(upstash, neon) == "investigate"

    def test_investigate_when_neon_variance_is_high(self) -> None:
        """A p95/p50 ratio above 5x on the Neon path blocks a decision."""
        upstash = LatencySample(p50_ms=8.0, p95_ms=10.0)
        neon = LatencySample(p50_ms=10.0, p95_ms=60.0)

        assert provider_recommendation(upstash, neon) == "investigate"

    def test_rejects_non_positive_p50(self) -> None:
        """A zero p50 cannot support a latency ratio decision."""
        with pytest.raises(ValueError, match="p50 latency must be positive"):
            provider_recommendation(
                LatencySample(p50_ms=8.0, p95_ms=10.0),
                LatencySample(p50_ms=0.0, p95_ms=1.0),
            )


class TestMonthlyCommandProjection:
    """The census projection applies documented ceilings to traffic counts."""

    def test_projection_multiplies_counts_by_flow_ceilings(self) -> None:
        """Bootstrap (4) and roll (5) ceilings scale observed counts."""
        projection = project_monthly_cache_commands({"bootstrap": 100, "roll": 10})

        assert projection.total_commands == 100 * 4 + 10 * 5
        assert projection.within_budget is True

    def test_small_traffic_stays_inside_budget(self) -> None:
        """A modest single-user census keeps the 150,000-command headroom."""
        assert project_monthly_cache_commands({"bootstrap": 20_000}).within_budget is True

    def test_heavy_traffic_breaches_budget(self) -> None:
        """A demanding census flags the 350,000-command ceiling breach."""
        projection = project_monthly_cache_commands({"roll": 100_000})

        assert projection.total_commands == 500_000
        assert projection.within_budget is False

    def test_budget_is_strictly_below_to_preserve_headroom(self) -> None:
        """Reaching the budget exactly does not count as within budget."""
        projection = project_monthly_cache_commands({"roll": 70_000})

        assert projection.total_commands == CONSERVATIVE_MONTHLY_COMMAND_BUDGET
        assert projection.within_budget is False

    def test_rejects_undocumented_flow(self) -> None:
        """An unknown flow cannot invent cache demand beyond the ceilings."""
        with pytest.raises(ValueError, match="undocumented cache flow"):
            project_monthly_cache_commands({"bootstrap": 1, "fabricated_flow": 1})

    def test_rejects_negative_flow_count(self) -> None:
        """Negative traffic counts are census corruption, not demand."""
        with pytest.raises(ValueError, match="must be non-negative"):
            project_monthly_cache_commands({"bootstrap": -1})

    def test_projection_dataclass_defaults_to_documented_budget(self) -> None:
        """The projection defaults to the conservative monthly budget constant."""
        assert (
            CacheCommandProjection(total_commands=0).budget_commands
            == CONSERVATIVE_MONTHLY_COMMAND_BUDGET
        )


class TestMemoBudgetNumbers:
    """The memo's budget ledger matches the instrumentation constants."""

    def test_free_allowance_application_budget_and_headroom(self) -> None:
        """500k allowance, 350k application budget, 150k (30%) headroom."""
        assert UPSTASH_FREE_MONTHLY_COMMANDS == 500_000
        assert CONSERVATIVE_MONTHLY_COMMAND_BUDGET == 350_000
        assert MONTHLY_HEADROOM_COMMANDS == 150_000
        assert MONTHLY_HEADROOM_COMMANDS / UPSTASH_FREE_MONTHLY_COMMANDS == pytest.approx(0.30)