"""Tests for the Neon egress monitor (issue #2833).

Covers normal growth, absolute threshold warning, anomaly warning,
period rollover, missing API response, and repeated polls during one
active warning.  All network access is mocked via httpx transports.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import httpx
import pytest

from app.services.neon_monitor import (
    ConsumptionSample,
    NeonEgressMonitor,
    NeonMonitorSettings,
    create_neon_monitor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**overrides: object) -> NeonMonitorSettings:
    """Build settings with test-safe defaults, overriding as needed."""
    defaults: dict[str, object] = {
        "neon_token": "test-token",
        "neon_project_id": "test-project",
        "neon_absolute_threshold_gb": 5.0,
        "neon_anomaly_delta_gb": 1.0,
        "neon_anomaly_factor": 3.0,
        "neon_poll_interval_seconds": 3600,
    }
    defaults.update(overrides)
    return NeonMonitorSettings(**defaults)  # type: ignore[arg-type]


def _consumption_response(public_bytes: int) -> httpx.MockTransport:
    """Return a mock transport serving a single consumption response."""
    return httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={"data": {"public_data_transfer_bytes": public_bytes}},
        )
    )


def _error_response() -> httpx.MockTransport:
    """Return a mock transport serving a 500 error."""
    return httpx.MockTransport(
        lambda _request: httpx.Response(500, text="Internal Server Error")
    )


def _make_monitor(
    transport: httpx.MockTransport,
    **settings_overrides: object,
) -> NeonEgressMonitor:
    """Create a monitor wired to a mock transport."""
    settings = _make_settings(**settings_overrides)
    monitor = NeonEgressMonitor(settings)
    monitor.client = httpx.AsyncClient(
        base_url="https://api.neon.tech",
        transport=transport,
        headers={"Authorization": f"Bearer {settings.neon_token}"},
    )
    return monitor


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNeonMonitorSettings:
    """Configuration validation tests."""

    def test_defaults(self) -> None:
        """Defaults are applied when only required fields are supplied."""
        settings = NeonMonitorSettings(neon_token="tok", neon_project_id="proj")
        assert settings.neon_absolute_threshold_gb == 5.0
        assert settings.neon_anomaly_delta_gb == 1.0
        assert settings.neon_anomaly_factor == 3.0
        assert settings.neon_poll_interval_seconds == 3600


class TestConsumptionSample:
    """Dataclass tests."""

    def test_construction(self) -> None:
        """ConsumptionSample stores timestamp, bytes, and month."""
        ts = datetime(2026, 9, 22, tzinfo=UTC)
        sample = ConsumptionSample(timestamp=ts, public_bytes=1_000_000, month="2026-09")
        assert sample.public_bytes == 1_000_000
        assert sample.month == "2026-09"


class TestNeonEgressMonitor:
    """Core monitor behaviour tests."""

    @pytest.mark.asyncio
    async def test_first_sample_records_first_sample_event(self) -> None:
        """First evaluation records a first_sample event."""
        monitor = _make_monitor(_consumption_response(500_000_000))
        try:
            sample = await monitor._fetch_monthly_consumption()
            assert sample is not None
            monitor.last_sample = sample
            monitor._evaluate_warnings(sample)
            assert len(monitor.events) == 1
            assert monitor.events[0]["type"] == "first_sample"
        finally:
            await monitor.close()

    @pytest.mark.asyncio
    async def test_normal_growth_logs_normal(self) -> None:
        """Small delta below thresholds logs a normal event."""
        monitor = _make_monitor(_consumption_response(100_000_000))
        try:
            # First sample
            sample1 = await monitor._fetch_monthly_consumption()
            assert sample1 is not None
            monitor.last_sample = sample1
            monitor._evaluate_warnings(sample1)
            assert monitor.events[-1]["type"] == "first_sample"

            # Second sample — small increase, below all thresholds
            sample2 = ConsumptionSample(
                timestamp=datetime.now(UTC),
                public_bytes=150_000_000,
                month=sample1.month,
            )
            monitor._evaluate_warnings(sample2)
            assert monitor.events[-1]["type"] == "normal"
        finally:
            await monitor.close()

    @pytest.mark.asyncio
    async def test_absolute_threshold_warning(self) -> None:
        """Usage exceeds the absolute threshold → warning fires."""
        monitor = _make_monitor(
            _consumption_response(4_000_000_000),
            neon_absolute_threshold_gb=5.0,
        )
        try:
            sample1 = await monitor._fetch_monthly_consumption()
            assert sample1 is not None
            monitor.last_sample = sample1
            monitor._evaluate_warnings(sample1)

            # Push past 5 GB
            sample2 = ConsumptionSample(
                timestamp=datetime.now(UTC),
                public_bytes=6_000_000_000,
                month=sample1.month,
            )
            monitor._evaluate_warnings(sample2)
            assert monitor.events[-1]["type"] == "warning"
            detail = monitor.events[-1]["data"]
            assert isinstance(detail, dict)
            assert detail["type"] == "absolute"
        finally:
            await monitor.close()

    @pytest.mark.asyncio
    async def test_anomaly_warning(self) -> None:
        """Sudden large delta triggers anomaly warning."""
        monitor = _make_monitor(
            _consumption_response(100_000_000),
            neon_anomaly_delta_gb=0.5,
            neon_anomaly_factor=2.0,
        )
        try:
            sample1 = await monitor._fetch_monthly_consumption()
            assert sample1 is not None
            monitor.last_sample = sample1
            monitor._evaluate_warnings(sample1)

            # Jump: 100 MB → 1.5 GB  (delta = 1.4 GB > 0.5 GB threshold)
            # delta_gb (1.4) >= factor (2.0) * last_gb (0.09) → True
            sample2 = ConsumptionSample(
                timestamp=datetime.now(UTC),
                public_bytes=1_500_000_000,
                month=sample1.month,
            )
            monitor._evaluate_warnings(sample2)
            assert monitor.events[-1]["type"] == "warning"
            detail = monitor.events[-1]["data"]
            assert isinstance(detail, dict)
            assert detail["type"] == "anomaly"
            assert detail["delta_bytes"] == 1_400_000_000
        finally:
            await monitor.close()

    @pytest.mark.asyncio
    async def test_period_rollover_resets_baseline(self) -> None:
        """Month change triggers rollover event and resets the baseline."""
        monitor = _make_monitor(_consumption_response(4_000_000_000))
        try:
            # First sample in September
            sample_sep = await monitor._fetch_monthly_consumption()
            assert sample_sep is not None
            # Force month to September for deterministic test
            sample_sep = ConsumptionSample(
                timestamp=sample_sep.timestamp,
                public_bytes=sample_sep.public_bytes,
                month="2026-09",
            )
            monitor.last_sample = sample_sep
            monitor._evaluate_warnings(sample_sep)

            # October sample — rollover
            sample_oct = ConsumptionSample(
                timestamp=datetime.now(UTC),
                public_bytes=200_000_000,
                month="2026-10",
            )
            monitor._evaluate_warnings(sample_oct)

            # Expect: period_rollover then first_sample
            types = [e["type"] for e in monitor.events]
            assert "period_rollover" in types
            # After rollover, the last event should be first_sample
            assert monitor.events[-1]["type"] == "first_sample"
            # Baseline reset to the new month's sample
            assert monitor.last_sample.month == "2026-10"
            assert monitor.last_sample.public_bytes == 200_000_000
        finally:
            await monitor.close()

    @pytest.mark.asyncio
    async def test_missing_api_response_returns_none(self) -> None:
        """A failing API request returns None and leaves state untouched."""
        monitor = _make_monitor(_error_response())
        try:
            sample = await monitor._fetch_monthly_consumption()
            assert sample is None
            assert monitor.last_sample is None
            assert len(monitor.events) == 0
        finally:
            await monitor.close()

    @pytest.mark.asyncio
    async def test_repeated_polls_during_active_warning(self) -> None:
        """Multiple polls while a warning is active keep logging warnings."""
        monitor = _make_monitor(
            _consumption_response(6_000_000_000),
            neon_absolute_threshold_gb=5.0,
        )
        try:
            sample1 = await monitor._fetch_monthly_consumption()
            assert sample1 is not None
            monitor.last_sample = sample1
            monitor._evaluate_warnings(sample1)
            # First poll is above threshold → warning
            assert monitor.events[-1]["type"] == "warning"

            # Second poll still above threshold
            sample2 = ConsumptionSample(
                timestamp=datetime.now(UTC),
                public_bytes=6_100_000_000,
                month=sample1.month,
            )
            monitor._evaluate_warnings(sample2)
            assert monitor.events[-1]["type"] == "warning"

            # Third poll still above threshold
            sample3 = ConsumptionSample(
                timestamp=datetime.now(UTC),
                public_bytes=6_200_000_000,
                month=sample1.month,
            )
            monitor._evaluate_warnings(sample3)
            assert monitor.events[-1]["type"] == "warning"

            # All three warnings recorded
            warnings = [e for e in monitor.events if e["type"] == "warning"]
            assert len(warnings) == 3
        finally:
            await monitor.close()

    @pytest.mark.asyncio
    async def test_fetch_returns_sample_with_correct_month(self) -> None:
        """The fetched sample carries the current ISO month."""
        monitor = _make_monitor(_consumption_response(42))
        try:
            sample = await monitor._fetch_monthly_consumption()
            assert sample is not None
            expected_month = datetime.now(UTC).strftime("%Y-%m")
            assert sample.month == expected_month
            assert sample.public_bytes == 42
        finally:
            await monitor.close()

    @pytest.mark.asyncio
    async def test_serialize_gb(self) -> None:
        """Bytes-to-gigabytes conversion."""
        monitor = _make_monitor(_consumption_response(0))
        try:
            assert monitor._serialize_gb(0) == 0.0
            assert monitor._serialize_gb(1024**3) == 1.0
            assert monitor._serialize_gb(5 * 1024**3) == 5.0
        finally:
            await monitor.close()


class TestCreateNeonMonitor:
    """Factory function tests."""

    def test_create_from_env(self) -> None:
        """Factory reads credentials from environment variables."""
        with patch.dict(
            "os.environ",
            {"NEON_TOKEN": "tok", "NEON_PROJECT_ID": "proj"},
        ):
            monitor = create_neon_monitor()
            assert monitor.settings.neon_token == "tok"
            assert monitor.settings.neon_project_id == "proj"
