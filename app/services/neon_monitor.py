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
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class NeonMonitorSettings(BaseModel):
    # Neon API authentication
    token: str = Field(..., env="NEON_TOKEN")
    project_id: str = Field(..., env="NEON_PROJECT_ID")

    # Thresholds (in gigabytes)
    absolute_threshold_gb: float = Field(5.0, env="NEON_ABSOLUTE_THRESHOLD_GB")
    anomaly_delta_gb: float = Field(1.0, env="NEON_ANOMALY_DELTA_GB")
    anomaly_factor: float = Field(3.0, env="NEON_ANOMALY_FACTOR")

    # Polling interval
    poll_interval_seconds: int = Field(3600, env="NEON_POLL_INTERVAL_SECONDS")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@dataclass
class ConsumptionSample:
    timestamp: datetime
    public_bytes: int
    month: str


class NeonEgressMonitor:
    def __init__(self, settings: NeonMonitorSettings):
        self.settings = settings
        self.client = httpx.AsyncClient(
            base_url="https://api.neon.tech", headers={"Authorization": f"Bearer {settings.token}"}
        )
        self.last_sample: ConsumptionSample | None = None
        self.events: list[dict[str, Any]] = []  # for test introspection

    async def _fetch_monthly_consumption(self) -> ConsumptionSample | None:
        """Query Neon for the current month's public data transfer.

        Returns ``None`` if the API request fails.
        """
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        url = f"/v1/projects/{self.settings.project_id}/consumption/periods"
        params = {"month": month}
        try:
            resp = await self.client.get(url, params=params, timeout=15.0)
            resp.raise_for_status()
            data = resp.json()
            # Expected shape:
            # {"data": {"public_data_transfer_bytes": 123456789}}
            public_bytes = int(data["data"]["public_data_transfer_bytes"])
            return ConsumptionSample(timestamp=datetime.now(timezone.utc), public_bytes=public_bytes, month=month)
        except Exception as exc:  # pragma: no cover - network failure
            logger.warning("Neon consumption fetch failed: %s", exc, exc_info=True)
            return None

    def _serialize_gb(self, bytes_: int) -> float:
        return round(bytes_ / (1024**3), 2)

    def _evaluate_warnings(self, sample: ConsumptionSample) -> None:
        """Determine if any thresholds are exceeded and log the event."""
        last = self.last_sample
        if last is None:
            # First sample, nothing to compare
            self._log_event("first_sample", sample)
            return
        delta = sample.public_bytes - last.public_bytes
        delta_gb = self._serialize_gb(delta)
        abs_warning = sample.public_bytes >= self.settings.absolute_threshold_gb * 1024**3
        anomaly = delta >= (self.settings.anomaly_delta_gb * 1024**3) and delta_gb >= self.settings.anomaly_factor * self._serialize_gb(last.public_bytes)
        if abs_warning or anomaly:
            detail = {"month": sample.month, "bytes": sample.public_bytes}
            if abs_warning:
                detail["type"] = "absolute"
            if anomaly:
                detail["type"] = "anomaly"
                detail["delta_bytes"] = delta
            self._log_event("warning", detail)
        else:
            self._log_event("normal", sample)

    def _log_event(self, event_type: str, data: Any) -> None:
        record = {"type": event_type, "timestamp": datetime.now(timezone.utc).isoformat(), "data": data}
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
                self.last_sample = sample
                self._evaluate_warnings(sample)
            await asyncio.sleep(self.settings.poll_interval_seconds)

    async def close(self) -> None:
        await self.client.aclose()


# Hook into application startup -------------------------------------------------

def create_neon_monitor() -> NeonEgressMonitor:
    return NeonEgressMonitor(NeonMonitorSettings())

# The monitor instance can be imported by the app and scheduled.
_monitored: NeonEgressMonitor | None = None

async def startup_event() -> None:
    global _monitored
    _monitored = create_neon_monitor()
    # schedule the monitor; noop when tests set TEST_ENVIRONMENT
    if not os.getenv("TEST_ENVIRONMENT"):
        asyncio.create_task(_monitored.start())

async def shutdown_event() -> None:
    if _monitored:
        await _monitored.close()
