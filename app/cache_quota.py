"""Cache quota guardrail: budget alerting and smoke-test throttling.

This module protects the configured monthly provider command budget (see
``docs/CACHE_COMMAND_BUDGET.md``) with two reactive boundaries:

* an *alert* band that fires a visible one-shot alert when observed application
  command usage crosses a configured fraction (default 80%) of the operating
  budget; and
* a *smoke-test throttle* band that, once usage reaches the hard budget,
  suppresses a bounded fraction of best-effort value writes so scheduled
  production smoke traffic and runaway rollouts cannot silently drain the
  provider quota and turn optional caching into a hard cache outage.

Critical generation invalidations (``INCR`` commands) are never throttled; only
non-essential value writes are subject to the smoke test.

The guardrail is transport-agnostic and privacy-safe: callers feed it the
observed command count from :mod:`app.cache_metrics`, and it reports policy
decisions. It never touches the network, cache keys, or user data, so it is
safe to consult on every request. Operators can surface the live snapshot
through :func:`observe_cache_quota` and the bounded ``/api/v1/health/cache-quota``
operational endpoint.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from dataclasses import dataclass

from app.cache_metrics import CONSERVATIVE_MONTHLY_COMMAND_BUDGET

logger = logging.getLogger(__name__)

DEFAULT_ALERT_FRACTION = 0.8
DEFAULT_SMOKE_TEST_DROP_RATE = 0.5



@dataclass(slots=True)
class QuotaState:
    """Snapshot of cache quota usage against the operating budget."""

    used: int
    budget: int
    usage_ratio: float
    alerted: bool
    throttling: bool
    remaining: int
    status: str

    @property
    def over_budget(self) -> bool:
        """Return whether observed usage has reached the hard budget."""
        return self.used >= self.budget


def _default_alert_sink(state: QuotaState) -> None:
    """Default alert sink logs a warning when the quota alert band is crossed."""
    logger.warning(
        "Cache quota alert: %d of %d budgeted commands used (%.1f%%); status=%s",
        state.used,
        state.budget,
        state.usage_ratio * 100,
        state.status,
    )


class QuotaGuardrail:
    """Track monthly cache command usage and decide alert/throttle policy.

    The guardrail is deliberately stateless about the calendar month. Callers
    report the running monthly command count via :meth:`assess` (or the module
    helper :func:`evaluate_cache_quota`); the guardrail compares it to the
    operating budget and emits policy decisions. Reset the alert latch with
    :meth:`reset` when a new billing month begins.
    """

    def __init__(
        self,
        budget: int = CONSERVATIVE_MONTHLY_COMMAND_BUDGET,
        alert_fraction: float = DEFAULT_ALERT_FRACTION,
        smoke_test_drop_rate: float = DEFAULT_SMOKE_TEST_DROP_RATE,
        alert_sink: Callable[[QuotaState], None] | None = None,
    ) -> None:
        """Configure the guardrail boundaries.

        Args:
            budget: Hard monthly application command budget; writes are
                smoke-test throttled once observed usage reaches it.
            alert_fraction: Fraction of ``budget`` that triggers a one-shot alert.
            smoke_test_drop_rate: Fraction of best-effort writes dropped while
                throttling is active (the smoke test exercises the DB path).
            alert_sink: Callable invoked once when the alert band is first crossed.
        """
        self.budget = budget
        self.alert_fraction = alert_fraction
        self.smoke_test_drop_rate = smoke_test_drop_rate
        self._alert_sink = alert_sink or _default_alert_sink
        self._alerted_once = False
        self._last_state: QuotaState | None = None

    def _snapshot(
        self,
        used: int,
        ratio: float,
        alerted: bool,
        throttling: bool,
        remaining: int,
        status: str,
    ) -> QuotaState:
        """Build an immutable state snapshot."""
        return QuotaState(
            used=used,
            budget=self.budget,
            usage_ratio=ratio,
            alerted=alerted,
            throttling=throttling,
            remaining=remaining,
            status=status,
        )

    def assess(self, used: int, *, fire_alert: bool = True) -> QuotaState:
        """Compare observed usage to the budget and update policy state.

        Args:
            used: Observed monthly cache command count.
            fire_alert: When ``False``, evaluate the alert band without invoking
                the alert sink and without consuming the one-shot latch, so a
                later ``fire_alert=True`` evaluation (e.g., the operator report)
                can still emit the alert.

        Returns:
            The resulting :class:`QuotaState`.
        """
        if used < 0:
            raise ValueError("observed cache command usage cannot be negative")
        ratio = used / self.budget if self.budget > 0 else float("inf")
        alerted = ratio >= self.alert_fraction
        throttling = used >= self.budget
        remaining = max(self.budget - used, 0)
        status = "over-budget" if throttling else ("near-limit" if alerted else "ok")

        if alerted and not self._alerted_once:
            if fire_alert:
                self._alert_sink(self._snapshot(used, ratio, alerted, throttling, remaining, status))
                self._alerted_once = True
            # When fire_alert is False (e.g., the hot cache-write path), do not
            # consume the latch so a later fire_alert=True evaluation (the operator
            # report) can still emit the one-shot alert at the 80% band.
        elif not alerted:
            # Usage fell back under the band (e.g., new month): re-arm the alert.
            self._alerted_once = False

        state = self._snapshot(used, ratio, alerted, throttling, remaining, status)
        self._last_state = state
        return state

    def should_throttle_write(self, *, rng: random.Random | None = None) -> bool:
        """Return whether a best-effort cache write should be dropped.

        Args:
            rng: Optional seeded RNG for deterministic tests; defaults to the
                process ``random`` instance.

        Returns:
            ``True`` when throttling is active and this write fell in the
            smoke-test drop sample.
        """
        state = self._last_state
        if state is None or not state.throttling:
            return False
        return (rng or random).random() < self.smoke_test_drop_rate

    @property
    def last_state(self) -> QuotaState | None:
        """Return the most recent assessed :class:`QuotaState`, if any."""
        return self._last_state

    @property
    def alerted(self) -> bool:
        """Return whether the alert band has been crossed since the last reset."""
        return self._alerted_once

    def reset(self) -> None:
        """Clear the alert latch and cached state (call at the start of a month)."""
        self._alerted_once = False
        self._last_state = None


# Process-wide guardrail consulted by the cache write path and the usage CLI.
quota_guardrail = QuotaGuardrail()

# Whether the smoke-test write-drop is armed. The alert band and budget report
# stay active regardless; only the aggressive drop of best-effort value writes is
# gated behind this flag. It is OFF by default so normal operation and the test
# suite never silently drop cache writes. An "evaluation" rollout enables it
# explicitly via CACHE_QUOTA_THROTTLE_ENABLED once the budget is being watched.
quota_throttle_enabled = False


def set_quota_throttle_enabled(enabled: bool) -> None:
    """Arm or disarm the smoke-test write-drop throttle.

    Args:
        enabled: When ``True``, the cache write path drops a bounded fraction of
            best-effort value writes once the observed monthly budget is reached.
    """
    global quota_throttle_enabled
    quota_throttle_enabled = enabled


def evaluate_cache_quota(used: int | None = None, *, fire_alert: bool = True) -> QuotaState:
    """Assess the current cache quota from observed application command usage.

    Args:
        used: Observed monthly command count; defaults to the live
            :data:`app.cache_metrics.cache_command_metrics` total.
        fire_alert: When ``False``, evaluate without invoking the alert sink.

    Returns:
        The resulting :class:`QuotaState`.
    """
    if used is None:
        # Lazy import keeps this guardrail importable without the cache stack so
        # operator tooling and focused tests can load its pure policy logic.
        from app.cache_metrics import cache_command_metrics

        used = cache_command_metrics.total()
    return quota_guardrail.assess(used, fire_alert=fire_alert)


def observe_cache_quota(used: int | None = None) -> QuotaState:
    """Read-only quota assessment for monitoring; never fires the alert sink.

    Args:
        used: Observed monthly command count; defaults to live metrics.

    Returns:
        The current :class:`QuotaState` without alert side effects.
    """
    return evaluate_cache_quota(used, fire_alert=False)


def should_throttle_cache_write(
    *, rng: random.Random | None = None, throttle_enabled: bool | None = None
) -> bool:
    """Return whether the next best-effort cache write should be smoke-test dropped.

    Args:
        rng: Optional seeded RNG for deterministic tests.
        throttle_enabled: Explicit arm state; defaults to the process-wide
            :data:`quota_throttle_enabled` flag. Callers that own an instance-scoped
            backend (for example ``UpstashCache``) pass their own flag so leaked
            process-wide guardrail state can never silently drop writes.

    Returns:
        ``True`` when throttling is active and this write is in the drop sample.
    """
    armed = quota_throttle_enabled if throttle_enabled is None else throttle_enabled
    if not armed:
        return False
    if quota_guardrail.last_state is None or not quota_guardrail.last_state.throttling:
        evaluate_cache_quota(fire_alert=False)
    return quota_guardrail.should_throttle_write(rng=rng)
