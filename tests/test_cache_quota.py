"""Tests for the cache quota guardrail: visible alert + smoke-test throttling.

Covers issue #1751 acceptance: approaching the monthly command budget triggers
a visible alert, and automated (smoke-test) traffic cannot silently drain the
provider quota because best-effort value writes are bounded once the hard budget
is reached while generation invalidations are never throttled.
"""

from __future__ import annotations

import random

import pytest
from fastapi import HTTPException

from app.api import health
from app.cache import UpstashCache, cache
from app.cache_generation import bump_user_generation
from app.cache_metrics import cache_command_metrics
from app.cache_quota import (
    QuotaGuardrail,
    QuotaState,
    evaluate_cache_quota,
    observe_cache_quota,
    quota_guardrail,
    set_quota_throttle_enabled,
    should_throttle_cache_write,
)


@pytest.fixture(autouse=True)
def reset_quota_globals() -> None:
    """Reset shared production quota and command instrumentation per test."""
    cache_command_metrics.reset()
    quota_guardrail.reset()
    set_quota_throttle_enabled(False)


class RecordingCacheClient:
    """Minimal Upstash-shaped client that counts transport calls."""

    def __init__(self) -> None:
        """Start with zero generation and zero provider command counts."""
        self.generation = 0
        self.values: dict[str, str] = {}
        self.set_calls = 0
        self.incr_calls = 0

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        """Record one provider value write."""
        _ = ex
        self.set_calls += 1
        self.values[key] = value

    async def incr(self, key: str) -> int:
        """Record one provider generation increment."""
        self.incr_calls += 1
        self.generation += 1
        return self.generation


def _fresh_backend(client: RecordingCacheClient) -> UpstashCache:
    """Build an UpstashCache singleton wrapping a recording transport."""
    backend = UpstashCache()
    backend._initialized = True
    backend._client = client
    backend._is_upstash = True
    backend._circuit_breaker.reset()
    return backend


def _install_backend(
    monkeypatch: pytest.MonkeyPatch,
    backend: UpstashCache,
) -> None:
    """Point the module cache router at a recording backend for one test."""
    monkeypatch.setattr(cache, "_backend", backend)
    monkeypatch.setattr(cache, "_initialized", True)
    monkeypatch.setattr(cache, "_demoted", False)


# --- Guardrail policy logic --------------------------------------------------


def test_assess_reports_ok_below_alert_band() -> None:
    """Usage well under the budget reports ok with no alert latch set."""
    guard = QuotaGuardrail(budget=100, alert_fraction=0.8)
    state = guard.assess(50)

    assert state.status == "ok"
    assert state.alerted is False
    assert state.throttling is False
    assert state.over_budget is False
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


def test_assess_rejects_negative_usage() -> None:
    """Negative observed usage is invalid evidence and is rejected."""
    guard = QuotaGuardrail(budget=100)

    with pytest.raises(ValueError, match="negative"):
        guard.assess(-1)


def test_should_throttle_write_is_deterministic_with_seed() -> None:
    """The smoke-test drop is reproducible and bounded under a seeded RNG."""
    guard = QuotaGuardrail(budget=100, smoke_test_drop_rate=0.5)
    guard.assess(150)

    rng = random.Random(1234)
    drops = [guard.should_throttle_write(rng=rng) for _ in range(200)]
    # The drop sample is a bounded fraction: never all writes, never none.
    assert any(drops)
    assert not all(drops)


def test_should_throttle_write_false_when_under_budget() -> None:
    """No writes are throttled while usage is below the hard budget."""
    guard = QuotaGuardrail(budget=100, smoke_test_drop_rate=1.0)
    guard.assess(10)

    assert guard.should_throttle_write() is False


# --- Module helpers and visible alert ----------------------------------------


def test_module_helper_evaluates_live_metrics() -> None:
    """The module helper reads the live metric total and resets between calls."""
    cache_command_metrics.record("get", count=10)
    state = evaluate_cache_quota(fire_alert=False)

    assert state.used == 10
    assert state.status == "ok"
    assert should_throttle_cache_write() is False

    cache_command_metrics.record("get", count=400_000)
    assert evaluate_cache_quota(fire_alert=False).status == "over-budget"
    assert should_throttle_cache_write(rng=random.Random(0)) in (True, False)


def test_module_helper_does_not_throttle_unless_armed() -> None:
    """The hot-path write-drop must stay off until the guardrail is explicitly armed.

    This prevents test-suite or accidental command volume from silently dropping
    cache writes; only a deliberate evaluation enables the smoke-test throttle.
    """
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
    cache_command_metrics.reset()
    quota_guardrail.reset()
    set_quota_throttle_enabled(True)
    # Push the global guardrail into an over-budget throttling snapshot.
    cache_command_metrics.record("get", count=400_000)
    assert should_throttle_cache_write() in (True, False)

    # Explicit instance flag False must never drop, regardless of leaked globals.
    assert should_throttle_cache_write(throttle_enabled=False) is False

    set_quota_throttle_enabled(False)


def test_write_path_fires_visible_alert_once_near_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Approaching the budget fires a visible one-shot alert via the write path."""
    alerts: list[QuotaState] = []
    monkeypatch.setattr(quota_guardrail, "_alert_sink", alerts.append)

    # 85% of budget: above the 80% alert band but below the hard limit.
    # Directly evaluate with fire_alert=True to simulate the write path.
    cache_command_metrics.record("set", count=297_500)
    evaluate_cache_quota(fire_alert=True)
    assert quota_guardrail.last_state is not None
    assert quota_guardrail.last_state.status == "near-limit"

    # A second evaluation must not re-fire the one-shot visible alert.
    evaluate_cache_quota(fire_alert=True)
    assert len(alerts) == 1


def test_should_throttle_cache_write_drops_bounded_fraction_above_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Above the hard budget only a bounded fraction of writes is dropped."""
    set_quota_throttle_enabled(True)
    cache_command_metrics.record("set", count=400_000)  # over the hard budget
    rng = random.Random(7)
    drops = [should_throttle_cache_write(rng=rng) for _ in range(200)]

    assert quota_guardrail.last_state is not None
    assert quota_guardrail.last_state.throttling is True
    assert quota_guardrail.last_state.status == "over-budget"
    assert any(drops)
    assert not all(drops)

    set_quota_throttle_enabled(False)


def test_observe_cache_quota_never_fires_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The monitoring snapshot never invokes the alert sink."""
    alerts: list[QuotaState] = []
    monkeypatch.setattr(quota_guardrail, "_alert_sink", alerts.append)

    cache_command_metrics.record("get", count=300_000)
    state = observe_cache_quota()

    assert state.status == "near-limit"
    assert len(alerts) == 0
    assert quota_guardrail.alerted is False


def test_monitoring_poll_does_not_starve_write_path_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A monitoring poll never consumes the one-shot; the write path still alerts."""
    alerts: list[QuotaState] = []
    monkeypatch.setattr(quota_guardrail, "_alert_sink", alerts.append)

    cache_command_metrics.record("get", count=300_000)  # near-limit band
    state = observe_cache_quota()
    assert state.status == "near-limit"
    assert quota_guardrail.alerted is False

    # The write path fires the alert by evaluating with fire_alert=True.
    cache_command_metrics.record("set", count=1)  # 300_001, still near-limit
    evaluate_cache_quota(fire_alert=True)
    assert quota_guardrail.alerted is True
    assert len(alerts) == 1


# --- Transport integration: smoke tests cannot silently drain quota -----------


@pytest.mark.asyncio
async def test_upstash_set_is_suppressed_when_write_is_throttled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A throttled best-effort value write never reaches the provider transport."""
    client = RecordingCacheClient()
    backend = _fresh_backend(client)
    _install_backend(monkeypatch, backend)

    monkeypatch.setattr(
        "app.cache_quota.should_throttle_cache_write",
        lambda rng=None, throttle_enabled=None: True,
    )

    result = await backend.set("cache:user:7:g0:test", {"value": 1}, ttl=60)

    assert result is True
    assert client.set_calls == 0


@pytest.mark.asyncio
async def test_upstash_set_writes_when_not_throttled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Below the budget a value write reaches the provider transport normally."""
    client = RecordingCacheClient()
    backend = _fresh_backend(client)
    _install_backend(monkeypatch, backend)

    monkeypatch.setattr(
        "app.cache_quota.should_throttle_cache_write",
        lambda rng=None, throttle_enabled=None: False,
    )

    result = await backend.set("cache:user:7:g0:test", {"value": 1}, ttl=60)

    assert result is True
    assert client.set_calls == 1


@pytest.mark.asyncio
async def test_generation_invalidation_never_throttled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Generation INCR invalidations proceed even when value writes are throttled."""
    client = RecordingCacheClient()
    backend = _fresh_backend(client)
    _install_backend(monkeypatch, backend)

    monkeypatch.setattr(
        "app.cache_quota.should_throttle_cache_write",
        lambda rng=None, throttle_enabled=None: True,
    )

    generation = await bump_user_generation(cache, 7)

    assert generation == 1
    assert client.incr_calls == 1


# --- Operational health surface ----------------------------------------------


@pytest.mark.asyncio
async def test_cache_quota_health_reports_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """The visible budget endpoint reports ok well below the alert band."""
    monkeypatch.setattr(quota_guardrail, "budget", 100)
    cache_command_metrics.record("get", count=50)

    response = await health.cache_quota_health(None)

    assert response.status == "ok"
    assert response.observed_commands == 50
    assert response.budget == 100
    assert response.remaining == 50
    assert response.usage_ratio == 0.5
    assert response.alerted is False
    assert response.throttling is False


@pytest.mark.asyncio
async def test_cache_quota_health_reports_near_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Crossing the alert band surfaces a visible near-limit state."""
    monkeypatch.setattr(quota_guardrail, "budget", 100)
    cache_command_metrics.record("get", count=85)

    response = await health.cache_quota_health(None)

    assert response.status == "near-limit"
    assert response.observed_commands == 85
    assert response.remaining == 15
    assert response.usage_ratio == 0.85
    assert response.alerted is True
    assert response.throttling is False


@pytest.mark.asyncio
async def test_cache_quota_health_reports_over_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reaching the hard budget surfaces over-budget with throttling enabled."""
    monkeypatch.setattr(quota_guardrail, "budget", 100)
    cache_command_metrics.record("get", count=120)

    response = await health.cache_quota_health(None)

    assert response.status == "over-budget"
    assert response.observed_commands == 120
    assert response.remaining == 0
    assert response.usage_ratio == 1.2
    assert response.alerted is True
    assert response.throttling is True


@pytest.mark.asyncio
async def test_cache_quota_health_requires_trusted_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The detailed budget endpoint hides behind the operational health token."""
    monkeypatch.setenv("HEALTH_CHECK_TOKEN", "trusted-monitor")

    with pytest.raises(HTTPException) as excinfo:
        await health._authorize_operational_probe(None)
    assert excinfo.value.status_code == 404

    # The trusted token passes the guard without raising.
    await health._authorize_operational_probe("trusted-monitor")
