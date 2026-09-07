"""Tests for durable Neon-backed cache command accounting (issue #2349).

Covers every acceptance criterion:
- Hot-path record is local/in-memory only (no Neon round trip).
- Neon writes are amortized across reserved blocks.
- Background replenishment begins at the low-water threshold.
- At most one replenishment task is outstanding per process.
- Neon slowness/failure never delays or fails a Redis operation.
- Multiple instances safely contribute to one Neon total.
- Health endpoint reports durable month-to-date usage.
- Health endpoint reports degraded status when accounting is unreliable.
- Month rollover requires no manual reset.
- Conservative overcounting on instance death is accepted.
- Existing alert/throttle behavior uses the durable count.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.cache_accounting import (
    DurableCacheAccounting,
    _current_month_key,
    cache_accounting,
)
from app.cache_metrics import cache_command_metrics
from app.cache_quota import observe_cache_quota, quota_guardrail


@pytest.fixture(autouse=True)
def reset_global_metrics() -> None:
    """Reset shared global counters per test to prevent state leakage."""
    cache_command_metrics.reset()
    quota_guardrail.reset()
    cache_accounting.reset()


@pytest.fixture
def accounting() -> DurableCacheAccounting:
    """Return a fresh accounting instance for unit tests."""
    return DurableCacheAccounting(block_size=100, low_water_mark=25)


# --- Hot-path: local only ---------------------------------------------------


class TestHotPathIsLocal:
    """record() must never touch the network or await."""

    def test_record_decrements_remaining(self, accounting: DurableCacheAccounting) -> None:
        """Each record call cheaply decrements the local counter."""
        accounting._remaining = 100
        accounting.record(1)
        assert accounting.remaining == 99

    def test_record_is_synchronous(self, accounting: DurableCacheAccounting) -> None:
        """record() must not be a coroutine or require an event loop."""
        accounting._remaining = 50
        result = accounting.record(5)
        assert result is None
        assert accounting.remaining == 45

    def test_record_never_negative(self, accounting: DurableCacheAccounting) -> None:
        """Consuming more than remaining floors at zero, never goes negative."""
        accounting._remaining = 3
        accounting.record(10)
        assert accounting.remaining == 0

    def test_record_does_not_touch_engine(self, accounting: DurableCacheAccounting) -> None:
        """record() never accesses the database engine."""
        accounting._remaining = 100
        accounting._engine = None
        accounting.record(1)
        assert accounting.remaining == 99


# --- Production funnel wiring ----------------------------------------------


class TestProductionFunnelWiring:
    """Every issued Redis command must consume a durable reservation slot."""

    def test_command_budget_record_consumes_durable_slot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The shared production budget decrements the durable reservation."""
        accounting = DurableCacheAccounting(block_size=100)
        accounting._remaining = 100
        monkeypatch.setattr("app.cache_generation.cache_accounting", accounting)

        from app.cache_generation import command_budget

        command_budget.record("generation_incr")

        assert accounting.remaining == 99

    def test_command_budget_record_multi_consumes_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Multi-command records consume matching durable slots."""
        accounting = DurableCacheAccounting(block_size=100)
        accounting._remaining = 100
        monkeypatch.setattr("app.cache_generation.cache_accounting", accounting)

        from app.cache_generation import command_budget

        command_budget.record("get", count=4)

        assert accounting.remaining == 96

    def test_command_budget_record_never_awaits_neon(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The funnel record stays synchronous end-to-end (no coroutine leak)."""
        accounting = DurableCacheAccounting(block_size=100)
        accounting._remaining = 100
        monkeypatch.setattr("app.cache_generation.cache_accounting", accounting)

        from app.cache_generation import command_budget

        with patch.object(accounting, "record", spec=DurableCacheAccounting.record) as fake:
            result = command_budget.record("set", count=1)

        assert result is None
        fake.assert_called_once_with(1)
        assert accounting.remaining == 100


# --- Block reservation (Neon) ------------------------------------------------


class TestBlockReservation:
    """_reserve_block atomically adds a block to the Neon row."""

    @pytest.mark.asyncio
    async def test_first_reservation_sets_neon_total(self) -> None:
        """Initial reservation creates the month row and returns the total."""
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE IF NOT EXISTS cache_usage "
                "(month TEXT PRIMARY KEY, commands INTEGER NOT NULL DEFAULT 0)"
            ))

        acc = DurableCacheAccounting(block_size=100)
        acc._engine = engine
        await acc._reserve_block()

        assert acc.neon_total == 100
        assert acc.remaining == 100
        assert acc.degraded is False

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_cumulative_reservations_sum_correctly(self) -> None:
        """Multiple reserves from the same or different 'instances' add up."""
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE IF NOT EXISTS cache_usage "
                "(month TEXT PRIMARY KEY, commands INTEGER NOT NULL DEFAULT 0)"
            ))

        acc1 = DurableCacheAccounting(block_size=50)
        acc1._engine = engine
        await acc1._reserve_block()
        assert acc1.neon_total == 50

        acc2 = DurableCacheAccounting(block_size=50)
        acc2._engine = engine
        await acc2._reserve_block()
        assert acc2.neon_total == 100

        assert acc1.remaining == 50
        assert acc2.remaining == 50

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_month_key_is_yyyy_mm(self) -> None:
        """The month key follows the YYYY-MM format."""
        key = _current_month_key()
        assert len(key) == 7
        assert key[4] == "-"
        year, month = key.split("-")
        assert 2024 <= int(year) <= 2099
        assert 1 <= int(month) <= 12


# --- Background replenishment ------------------------------------------------


class TestBackgroundReplenishment:
    """Background task triggers at the low-water mark."""

    @pytest.mark.asyncio
    async def test_replenishment_starts_when_below_low_water(self) -> None:
        """When remaining crosses low-water, the background loop triggers."""
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE IF NOT EXISTS cache_usage "
                "(month TEXT PRIMARY KEY, commands INTEGER NOT NULL DEFAULT 0)"
            ))

        acc = DurableCacheAccounting(block_size=100, low_water_mark=25, replenish_interval=0.05)
        acc._engine = engine
        await acc._reserve_block()

        # Consume down to low-water mark
        acc.record(80)
        assert acc.remaining == 20

        # Initialize the background loop
        acc._initialized = True
        acc._replenish_task = asyncio.create_task(
            acc._background_replenish(),
            name="test-replenish",
        )

        # Wait for replenishment to trigger (interval is 0.05s in test)
        await asyncio.sleep(0.2)

        # The remaining should have been replenished
        assert acc.remaining > 25

        await acc.close()
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_only_one_replenishment_outstanding(self) -> None:
        """At most one background task runs per process."""
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE IF NOT EXISTS cache_usage "
                "(month TEXT PRIMARY KEY, commands INTEGER NOT NULL DEFAULT 0)"
            ))

        acc = DurableCacheAccounting(
            block_size=100, low_water_mark=25, replenish_interval=0.05
        )
        acc._engine = engine
        await acc._reserve_block()
        acc._initialized = True
        acc._replenish_task = asyncio.create_task(
            acc._background_replenish(), name="test-replenish"
        )

        # Consume and let multiple cycles run
        acc.record(80)
        await asyncio.sleep(0.3)

        # There should only be one task (the one we started)
        assert acc._replenish_task is not None
        assert not acc._replenish_task.done() or acc._replenish_task.cancelled()

        await acc.close()
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_replenishment_suppressed_above_low_water(self) -> None:
        """No replenishment happens while remaining > low_water_mark."""
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE IF NOT EXISTS cache_usage "
                "(month TEXT PRIMARY KEY, commands INTEGER NOT NULL DEFAULT 0)"
            ))

        acc = DurableCacheAccounting(
            block_size=100, low_water_mark=25, replenish_interval=0.05
        )
        acc._engine = engine
        await acc._reserve_block()
        acc._initialized = True
        acc._replenish_task = asyncio.create_task(
            acc._background_replenish(), name="test-replenish"
        )

        # Don't consume enough to trigger low water
        acc.record(10)
        initial_neon = acc.neon_total
        await asyncio.sleep(0.2)

        # No new Neon reservation should have happened
        assert acc.neon_total == initial_neon

        await acc.close()
        await engine.dispose()


# --- Neon failure never delays Redis ----------------------------------------


class TestNeonFailureIsolation:
    """Redis operations proceed even when Neon is down."""

    @pytest.mark.asyncio
    async def test_initialize_failure_marks_degraded(self) -> None:
        """When Neon is unreachable at init, accounting marks degraded."""
        engine = create_async_engine("sqlite+aiosqlite://")
        # Do NOT create the cache_usage table, so queries will fail

        acc = DurableCacheAccounting(block_size=100)
        await acc.initialize(engine)

        assert acc.degraded is True
        assert acc.initialized is False

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_replenishment_failure_marks_degraded(self) -> None:
        """When Neon fails during replenishment, accounting stays degraded."""
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE IF NOT EXISTS cache_usage "
                "(month TEXT PRIMARY KEY, commands INTEGER NOT NULL DEFAULT 0)"
            ))

        acc = DurableCacheAccounting(
            block_size=100, low_water_mark=25, replenish_interval=0.05
        )
        await acc.initialize(engine)
        assert acc.degraded is False

        # Dispose the engine to simulate Neon failure
        await engine.dispose()

        # Consume to trigger replenishment
        acc.record(80)
        acc._replenish_task = asyncio.create_task(
            acc._background_replenish(), name="test-replenish"
        )

        await asyncio.sleep(0.3)

        assert acc.degraded is True

    @pytest.mark.asyncio
    async def test_redis_record_never_blocks_on_neon(self) -> None:
        """record() always returns immediately regardless of Neon state."""
        acc = DurableCacheAccounting(block_size=100)
        acc._remaining = 1000
        acc._engine = None

        start = time.monotonic()
        for _ in range(1000):
            acc.record(1)
        elapsed = time.monotonic() - start

        # 1000 decrements should take well under 100ms
        assert elapsed < 0.1
        assert acc.remaining == 900


# --- Multiple instances contribute to one total -----------------------------


class TestMultiInstance:
    """Simulates concurrent Vercel instances reserving blocks."""

    @pytest.mark.asyncio
    async def test_two_instances_contribute_to_one_neon_total(self) -> None:
        """Two accounting instances on the same Neon see one combined total."""
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE IF NOT EXISTS cache_usage "
                "(month TEXT PRIMARY KEY, commands INTEGER NOT NULL DEFAULT 0)"
            ))

        acc1 = DurableCacheAccounting(block_size=100)
        acc1._engine = engine
        await acc1._reserve_block()

        acc2 = DurableCacheAccounting(block_size=100)
        acc2._engine = engine
        await acc2._reserve_block()

        # acc1 saw 100 when it reserved; acc2 saw 200 after both reserved
        assert acc1.neon_total == 100
        assert acc2.neon_total == 200

        # Each has its own local remaining
        acc1.record(30)
        acc2.record(20)
        assert acc1.remaining == 70
        assert acc2.remaining == 80

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_three_instances_reserve_sequentially(self) -> None:
        """Three instances each reserve and see the cumulative total."""
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE IF NOT EXISTS cache_usage "
                "(month TEXT PRIMARY KEY, commands INTEGER NOT NULL DEFAULT 0)"
            ))

        accounts = []
        for _ in range(3):
            acc = DurableCacheAccounting(block_size=50)
            acc._engine = engine
            await acc._reserve_block()
            accounts.append(acc)

        # Third instance sees 150 total
        assert accounts[2].neon_total == 150

        await engine.dispose()


# --- Health endpoint reports durable total ----------------------------------


class TestHealthEndpointDurable:
    """The health endpoint uses durable Neon total, not process-local metrics."""

    def test_observe_uses_durable_when_available(self) -> None:
        """observe_cache_quota reads from durable accounting when healthy."""
        from app.cache_metrics import cache_command_metrics
        from app.cache_accounting import cache_accounting

        # Simulate some process-local commands
        cache_command_metrics.record("get", count=50)

        # Simulate durable accounting being initialized and healthy
        with patch.object(cache_accounting, "_initialized", True), \
             patch.object(cache_accounting, "_degraded", False), \
             patch.object(cache_accounting, "_neon_total", 300):
            state = observe_cache_quota()

        # Should use the durable total (300), not process-local (50)
        assert state.used == 300
        assert state.degraded is False

    def test_observe_falls_back_to_process_local_when_degraded(self) -> None:
        """When durable accounting is degraded, observe uses process-local."""
        from app.cache_metrics import cache_command_metrics
        from app.cache_accounting import cache_accounting

        cache_command_metrics.record("get", count=75)

        with patch.object(cache_accounting, "_initialized", True), \
             patch.object(cache_accounting, "_degraded", True), \
             patch.object(cache_accounting, "_neon_total", 300):
            state = observe_cache_quota()

        # Should use process-local (75), not durable (300)
        assert state.used == 75
        assert state.degraded is True

    def test_observe_falls_back_when_not_initialized(self) -> None:
        """When durable accounting is not initialized, observe uses process-local."""
        from app.cache_metrics import cache_command_metrics
        from app.cache_accounting import cache_accounting

        cache_command_metrics.record("set", count=25)

        with patch.object(cache_accounting, "_initialized", False), \
             patch.object(cache_accounting, "_degraded", True):
            state = observe_cache_quota()

        assert state.used == 25
        assert state.degraded is True

    @pytest.mark.asyncio
    async def test_health_response_includes_degraded_field(self) -> None:
        """CacheQuotaHealthResponse now carries a degraded boolean."""
        from app.api.health import CacheQuotaHealthResponse

        response = CacheQuotaHealthResponse(
            status="ok",
            observed_commands=0,
            budget=350_000,
            remaining=350_000,
            usage_ratio=0.0,
            alerted=False,
            throttling=False,
            degraded=True,
        )
        assert response.degraded is True

    @pytest.mark.asyncio
    async def test_health_response_degraded_defaults_false(self) -> None:
        """CacheQuotaHealthResponse defaults degraded to False."""
        from app.api.health import CacheQuotaHealthResponse

        response = CacheQuotaHealthResponse(
            status="ok",
            observed_commands=0,
            budget=350_000,
            remaining=350_000,
            usage_ratio=0.0,
            alerted=False,
            throttling=False,
        )
        assert response.degraded is False


# --- Month rollover ----------------------------------------------------------


class TestMonthRollover:
    """Month rollover uses a new key automatically; no cron needed."""

    @pytest.mark.asyncio
    async def test_new_month_creates_fresh_row(self) -> None:
        """A different month key creates a separate Neon row."""
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE IF NOT EXISTS cache_usage "
                "(month TEXT PRIMARY KEY, commands INTEGER NOT NULL DEFAULT 0)"
            ))

        acc = DurableCacheAccounting(block_size=100)
        acc._engine = engine
        acc._month_key = "2026-08"
        await acc._reserve_block()
        assert acc.neon_total == 100

        # Simulate month rollover
        acc._month_key = "2026-09"
        await acc._reserve_block()
        # The September row starts fresh at 100
        assert acc.neon_total == 100

        await engine.dispose()

    def test_current_month_key_format(self) -> None:
        """_current_month_key returns YYYY-MM for the current UTC date."""
        key = _current_month_key()
        now = datetime.now(UTC)
        assert key == now.strftime("%Y-%m")


# --- Conservative overcounting -----------------------------------------------


class TestConservativeOvercounting:
    """Instance death with unused reserved slots causes safe overcounting."""

    def test_unused_slots_not_subtracted_from_neon(self) -> None:
        """When an instance dies, its unused slots stay in the Neon total."""
        acc = DurableCacheAccounting(block_size=100)
        acc._neon_total = 300
        acc._remaining = 70

        # The durable total remains 300, not 300 - 70 = 230
        assert acc.durable_total() == 300

    def test_overcounting_is_conservative(self) -> None:
        """Overcounting means reporting MORE usage, never LESS."""
        acc = DurableCacheAccounting(block_size=100)
        acc._neon_total = 200
        acc._remaining = 100

        # True usage might be 100 (200 - 100 unused), but we report 200
        assert acc.durable_total() >= 200


# --- Snapshot and accessor methods ------------------------------------------


class TestAccessors:
    """Read-only accessors reflect the current accounting state."""

    def test_snapshot_returns_dict(self) -> None:
        """snapshot() returns a detached dict for metrics consumers."""
        acc = DurableCacheAccounting()
        acc._neon_total = 500
        snap = acc.snapshot()
        assert snap == {"durable_commands": 500}

    def test_durable_total_zero_when_neon_never_reached(self) -> None:
        """durable_total() returns 0 when Neon has never been queried."""
        acc = DurableCacheAccounting()
        assert acc.durable_total() == 0
        assert acc.neon_total is None

    def test_month_key_exposed(self) -> None:
        """month_key returns the current YYYY-MM period."""
        acc = DurableCacheAccounting()
        assert acc.month_key == _current_month_key()


# --- Alert/throttle integration with durable count ---------------------------


class TestDurableQuotaIntegration:
    """Existing alert/throttle behavior uses the durable count correctly."""

    def test_near_limit_uses_durable_count(self) -> None:
        """The guardrail fires alerts based on the durable total."""
        quota_guardrail.reset()

        # Simulate durable total at 85% of budget
        state = observe_cache_quota(used=297_500)
        assert state.status == "near-limit"
        assert state.used == 297_500

    def test_over_budget_uses_durable_count(self) -> None:
        """The guardrail enables throttling based on the durable total."""
        quota_guardrail.reset()

        state = observe_cache_quota(used=400_000)
        assert state.status == "over-budget"
        assert state.throttling is True

    def test_ok_status_uses_durable_count(self) -> None:
        """Well below budget reports ok."""
        quota_guardrail.reset()

        state = observe_cache_quota(used=10_000)
        assert state.status == "ok"


# --- Close/cleanup -----------------------------------------------------------


class TestCleanup:
    """Proper shutdown cancels background tasks."""

    @pytest.mark.asyncio
    async def test_close_cancels_replenishment_task(self) -> None:
        """close() cancels the background replenishment task."""
        acc = DurableCacheAccounting()
        acc._initialized = True

        async def _noop() -> None:
            while True:
                await asyncio.sleep(10)

        acc._replenish_task = asyncio.create_task(_noop())
        task = acc._replenish_task

        await acc.close()

        assert task.cancelled()
        assert acc.initialized is False

    @pytest.mark.asyncio
    async def test_close_without_task_is_safe(self) -> None:
        """close() is safe when no replenishment task exists."""
        acc = DurableCacheAccounting()
        await acc.close()
        assert acc.initialized is False

    @pytest.mark.asyncio
    async def test_initialize_is_idempotent(self) -> None:
        """initialize() is safe to call multiple times."""
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE IF NOT EXISTS cache_usage "
                "(month TEXT PRIMARY KEY, commands INTEGER NOT NULL DEFAULT 0)"
            ))

        acc = DurableCacheAccounting(block_size=100)
        acc._engine = engine
        await acc._reserve_block()

        # Second initialize is a no-op
        await acc.initialize(engine)

        assert acc.initialized is True

        await acc.close()
        await engine.dispose()
