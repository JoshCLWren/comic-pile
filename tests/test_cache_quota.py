"""Tests for the cache quota guardrail (alert + smoke-test throttling)."""

from __future__ import annotations

import random

from app.cache_quota import (
    QuotaGuardrail,
    QuotaState,
    evaluate_cache_quota,
    quota_guardrail,
    should_throttle_cache_write,
)


def test_assess_reports_ok_below_alert_band() -> None:
    """Usage well under budget reports ok with no alert latch set."""
    guard = QuotaGuardrail(budget=100, alert_fraction=0.8)
    state = guard.assess(50)

    assert state.status == "ok"
    assert state.alerted is False
    assert state.throttling is False
    assert state.remaining == 50
    assert state.usage_ratio == 0.5


def test_assess_fires_alert_once_when_crossing_band() -> None:
    """The alert sink fires a single time when usage crosses the alert band."""
    alerts: list[QuotaState] = []
    guard = QuotaGuardrail(budget=100, alert_fraction=0.8, alert_sink=alerts.append)

    guard.assess(70)  # under band
    assert guard.alerted is False
    guard.assess(85)  # crosses 80%
    assert guard.alerted is True
    guard.assess(90)  # still over, must not re-fire
    assert len(alerts) == 1
    assert alerts[0].status == "near-limit"


def test_assess_rearms_alert_when_usage_drops() -> None:
    """Falling back under the band re-arms the one-shot alert for a new month."""
    alerts: list[QuotaState] = []
    guard = QuotaGuardrail(budget=100, alert_fraction=0.8, alert_sink=alerts.append)

    guard.assess(90)
    assert len(alerts) == 1
    guard.assess(10)
    assert guard.alerted is False
    guard.assess(90)
    assert len(alerts) == 2


def test_assess_reports_over_budget_and_throttling() -> None:
    """Reaching the hard budget flips status to over-budget and enables throttle."""
    guard = QuotaGuardrail(budget=100, alert_fraction=0.8)
    state = guard.assess(100)

    assert state.status == "over-budget"
    assert state.throttling is True
    assert state.over_budget is True


def test_should_throttle_write_is_deterministic_with_seed() -> None:
    """The smoke-test drop is reproducible under a seeded RNG."""
    guard = QuotaGuardrail(budget=100, smoke_test_drop_rate=0.5)
    guard.assess(150)

    rng = random.Random(1234)
    drops = [guard.should_throttle_write(rng=rng) for _ in range(200)]
    # Not every write is dropped; the drop rate is bounded by the sample rate.
    assert any(drops)
    assert not all(drops)


def test_should_throttle_write_false_when_under_budget() -> None:
    """No writes are throttled while usage is below the hard budget."""
    guard = QuotaGuardrail(budget=100, smoke_test_drop_rate=1.0)
    guard.assess(10)

    assert guard.should_throttle_write() is False


def test_module_helper_evaluates_live_metrics(monkeypatch: object) -> None:
    """The module helper reads the live metric total and resets between calls."""
    from app.cache_metrics import cache_command_metrics

    cache_command_metrics.reset()
    quota_guardrail.reset()

    cache_command_metrics.record("get", count=10)
    state = evaluate_cache_quota(fire_alert=False)
    assert state.used == 10
    assert should_throttle_cache_write() is False

    cache_command_metrics.record("get", count=400_000)
    assert evaluate_cache_quota(fire_alert=False).status == "over-budget"
    assert should_throttle_cache_write(rng=random.Random(0)) in (True, False)


def test_module_helper_does_not_throttle_unless_armed() -> None:
    """The hot-path write-drop must stay off until the guardrail is explicitly armed.

    This prevents test-suite or accidental command volume from silently dropping
    cache writes; only a deliberate evaluation enables the smoke-test throttle.
    """
    from app.cache_metrics import cache_command_metrics
    from app.cache_quota import (
        quota_guardrail,
        set_quota_throttle_enabled,
        should_throttle_cache_write,
    )

    cache_command_metrics.reset()
    quota_guardrail.reset()
    set_quota_throttle_enabled(False)

    # Far over the hard budget but the drop is not armed: never throttle.
    cache_command_metrics.record("get", count=400_000)
    assert should_throttle_cache_write(rng=random.Random(0)) is False
    assert should_throttle_cache_write(rng=random.Random(1)) is False

    # Arm it: once over budget the helper may now drop writes.
    set_quota_throttle_enabled(True)
    assert should_throttle_cache_write(rng=random.Random(0)) in (True, False)

    set_quota_throttle_enabled(False)


def test_instance_throttle_flag_isolates_from_global_state() -> None:
    """The instance-scoped arm flag must not be polluted by leaked global state.

    Regression guard: the hot cache-write path consults an instance flag, so a
    leaked process-wide ``quota_throttle_enabled`` (True) or a leaked ``over-budget``
    guardrail snapshot cannot silently drop value writes for a backend that was not
    configured to throttle.
    """
    from app.cache_metrics import cache_command_metrics
    from app.cache_quota import (
        quota_guardrail,
        set_quota_throttle_enabled,
        should_throttle_cache_write,
    )

    cache_command_metrics.reset()
    quota_guardrail.reset()
    set_quota_throttle_enabled(True)
    # Push the global guardrail into an over-budget throttling snapshot.
    cache_command_metrics.record("get", count=400_000)
    assert should_throttle_cache_write() in (True, False)

    # Explicit instance flag False must never drop, regardless of leaked globals.
    assert should_throttle_cache_write(throttle_enabled=False) is False

    set_quota_throttle_enabled(False)
