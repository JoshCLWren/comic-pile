"""Neon usage monitoring.

This module implements a placeholder Neon egress monitor according to
issue #2833.  The implementation focuses on the architectural
requirements rather than a fully fledged production integration.

Key points
-----------
* Reads consumption from the Neon API using a bearer ``NEON_TOKEN``.
* Configuration values (thresholds, project id) are loaded from
  environment variables via :class:`NeonMonitorSettings`.
* The monitor exposes an async ``start`` coroutine that can be scheduled
  during application startup, mirroring existing background tasks.
* For testing purposes the monitor returns log messages in a structured
  format via a simple in-memory `events` list – this enables isolation
  from external network and GitHub actions.

The design intentionally keeps external side effects minimal to make
unit‑testing straightforward.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class NeonMonitorSettings(BaseSettings):
    """Configuration settings for the Neon egress monitor.

    All thresholds and credentials are loaded from environment variables.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Neon API authentication
    neon_token: str = Field(
        ...,
        validation_alias=AliasChoices("NEON_TOKEN", "neon_token"),
    )
    neon_project_id: str = Field(
        ...,
        validation_alias=AliasChoices("NEON_PROJECT_ID", "neon_project_id"),
    )

    # Thresholds (in gigabytes)
    neon_absolute_threshold_gb: float = Field(
        5.0,
        validation_alias=AliasChoices(
            "NEON_ABSOLUTE_THRESHOLD_GB", "neon_absolute_threshold_gb"
        ),
    )
    neon_anomaly_delta_gb: float = Field(
        1.0,
        validation_alias=AliasChoices("NEON_ANOMALY_DELTA_GB", "neon_anomaly_delta_gb"),
    )
    neon_anomaly_factor: float = Field(
        3.0,
        validation_alias=AliasChoices("NEON_ANOMALY_FACTOR", "neon_anomaly_factor"),
    )

    # Polling interval
    neon_poll_interval_seconds: int = Field(
        3600,
        validation_alias=AliasChoices(
            "NEON_POLL_INTERVAL_SECONDS", "neon_poll_interval_seconds"
        ),
    )


@dataclass
class ConsumptionSample:
    """A single Neon consumption sample for a given period.

    Attributes:
        timestamp: When the sample was collected.
        public_bytes: Public data transfer in bytes.
        month: The ISO month identifier (e.g. "2026-09").
    """

    timestamp: datetime
    public_bytes: int
    month: str


class NeonEgressMonitor:
    """Monitors Neon egress and alerts on abnormal spend patterns.

    Polls the Neon consumption API, evaluates configured thresholds,
    and records events for observability.
    """

    def __init__(self, settings: NeonMonitorSettings) -> None:
        """Initialize the monitor with its settings and HTTP client.

        Args:
            settings: The Neon monitor configuration.
        """
        self.settings = settings
        self.client = httpx.AsyncClient(
            base_url="https://api.neon.tech",
            headers={"Authorization": f"Bearer {settings.neon_token}"},
        )
        self.last_sample: ConsumptionSample | None = None
        self.events: list[dict[str, object]] = []

    async def _fetch_monthly_consumption(self) -> ConsumptionSample | None:
        """Query Neon for the current month's public data transfer.

        Returns ``None`` if the API request fails.
        """
        month = datetime.now(UTC).strftime("%Y-%m")
        url = f"/v1/projects/{self.settings.neon_project_id}/consumption/periods"
        params = {"month": month}
        try:
            resp = await self.client.get(url, params=params, timeout=15.0)
            resp.raise_for_status()
            data = resp.json()
            # Expected shape:
            # {"data": {"public_data_transfer_bytes": 123456789}}
            public_bytes = int(data["data"]["public_data_transfer_bytes"])
            return ConsumptionSample(
                timestamp=datetime.now(UTC),
                public_bytes=public_bytes,
                month=month,
            )
        except Exception as exc:  # pragma: no cover - network failure
            logger.warning("Neon consumption fetch failed: %s", exc, exc_info=True)
            return None

    def _serialize_gb(self, bytes_: int) -> float:
        """Convert bytes to gigabytes."""
        return round(bytes_ / (1024**3), 2)

    def _evaluate_warnings(self, sample: ConsumptionSample) -> None:
        """Determine if any thresholds are exceeded and log the event."""
        last = self.last_sample
        if last is None or sample is last:
            # First sample or identical resample — establish baseline
            self._log_event("first_sample", sample)
            self.last_sample = sample
            return

        # Period rollover: if the sample is from a different month than the
        # last sample, the delta is not meaningful.  Record the rollover and
        # reset the baseline so the new period starts clean.
        if sample.month != last.month:
            self._log_event(
                "period_rollover",
                {
                    "previous_month": last.month,
                    "current_month": sample.month,
                    "previous_bytes": last.public_bytes,
                    "current_bytes": sample.public_bytes,
                },
            )
            self.last_sample = sample
            self._log_event("first_sample", sample)
            return

        delta = sample.public_bytes - last.public_bytes
        delta_gb = self._serialize_gb(delta)
        abs_warning = (
            sample.public_bytes >= self.settings.neon_absolute_threshold_gb * 1024**3
        )
        anomaly_threshold = self.settings.neon_anomaly_delta_gb * 1024**3
        anomaly_baseline = self.settings.neon_anomaly_factor * self._serialize_gb(
            last.public_bytes
        )
        anomaly = delta >= anomaly_threshold and delta_gb >= anomaly_baseline

        if abs_warning or anomaly:
            detail: dict[str, object] = {
                "month": sample.month,
                "bytes": sample.public_bytes,
            }
            if abs_warning:
                detail["type"] = "absolute"
            if anomaly:
                detail["type"] = "anomaly"
                detail["delta_bytes"] = delta
            self._log_event("warning", detail)
        else:
            self._log_event("normal", sample)
        self.last_sample = sample

    def _log_event(self, event_type: str, data: object) -> None:
        """Record a monitor event for observability.

        Args:
            event_type: The category of event (e.g. "warning", "normal").
            data: The payload associated with the event.
        """
        record = {
            "type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            "data": data,
        }
        logger.info("NeonMonitor event: %s", record)
        self.events.append(record)

    async def start(self) -> None:
        """Begin periodic sampling.

        This coroutine can be awaited in an ``asyncio`` loop or attached as a
        FastAPI background task.
        """
        while True:
            sample = await self._fetch_monthly_consumption()
            if sample:
                self._evaluate_warnings(sample)
            await asyncio.sleep(self.settings.neon_poll_interval_seconds)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self.client.aclose()


# Hook into application startup -------------------------------------------------


def create_neon_monitor() -> NeonEgressMonitor:
    """Create a NeonEgressMonitor instance from environment settings."""
    return NeonEgressMonitor(NeonMonitorSettings())


# The monitor instance can be imported by the app and scheduled.
_monitored: NeonEgressMonitor | None = None


async def startup_event() -> None:
    """Initialize the monitor and schedule periodic sampling."""
    global _monitored
    _monitored = create_neon_monitor()
    # schedule the monitor; noop when tests set TEST_ENVIRONMENT
    if not os.getenv("TEST_ENVIRONMENT"):
        asyncio.create_task(_monitored.start())


async def shutdown_event() -> None:
    """Gracefully shut down the monitor's HTTP client."""
    if _monitored:
        await _monitored.close()
