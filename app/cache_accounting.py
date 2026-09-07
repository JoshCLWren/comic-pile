"""Durable month-to-date cache command accounting backed by Neon.

Replaces the process-local ``CacheCommandMetrics`` total with a Neon-backed
aggregate so every Vercel instance observes the true month-to-date command
count.  The Redis hot path is never slowed: each ``record`` call is a cheap
local counter decrement.  Neon writes happen only when reserving command
*blocks* and are amortized heavily.

Architecture
~~~~~~~~~~~~
1. A tiny ``cache_usage`` row per calendar month stores the running Neon total.
2. On startup each process atomically reserves a **block** of commands
   (default 100) via ``INSERT ... ON CONFLICT DO UPDATE ... RETURNING``.
3. A process-local ``remaining`` counter tracks how many of the reserved
   block the process may still consume without another Neon trip.
4. When ``remaining`` crosses the **low-water mark** (default 25) a
   single background asyncio task requests the next block.
5. At most one replenishment task is outstanding per process; duplicate
   scheduling is suppressed.
6. If Neon is unavailable, the background task logs degradation and
   retries on the next loop.  Redis operations are never delayed or
   blocked.

Health endpoint
~~~~~~~~~~~~~~~
``durable_total`` returns the month-to-date Neon aggregate.  The caller
may subtract unused local reservations for a tighter per-process
estimate, but the Neon row alone is the authoritative source for
cross-instance month-to-date usage.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

# Tunables -----------------------------------------------------------
BLOCK_SIZE = 100
LOW_WATER_MARK = 25
REPLENISH_INTERVAL_SECONDS = 5.0


def _current_month_key() -> str:
    """Return the ``YYYY-MM`` month key for the current UTC date."""
    return datetime.now(UTC).strftime("%Y-%m")


class DurableCacheAccounting:
    """Month-to-date command accounting backed by a Neon row.

    The accounting is safe to call from the synchronous Redis hot path:
    ``record`` never awaits and never touches the network.  Neon writes
    happen only during block reservation in a background asyncio task.
    """

    def __init__(
        self,
        block_size: int = BLOCK_SIZE,
        low_water_mark: int = LOW_WATER_MARK,
        replenish_interval: float = REPLENISH_INTERVAL_SECONDS,
    ) -> None:
        """Initialise accounting without starting any Neon activity.

        Args:
            block_size: Number of commands to reserve per Neon round trip.
            low_water_mark: Remaining-slot threshold that triggers
                background replenishment.
            replenish_interval: Seconds between background replenishment
                loops.
        """
        self._block_size = block_size
        self._low_water_mark = low_water_mark
        self._replenish_interval = replenish_interval

        self._remaining = 0
        self._reserved_total = 0
        self._neon_total: int | None = None
        self._degraded = True
        self._month_key = _current_month_key()

        self._engine: AsyncEngine | None = None
        self._initialized = False
        self._replenish_task: asyncio.Task[None] | None = None

    # -- Lifecycle --------------------------------------------------------

    async def initialize(self, engine: AsyncEngine) -> None:
        """Reserve the initial block from Neon and arm background replenishment.

        Args:
            engine: Shared async engine whose pool already targets Neon.
        """
        if self._initialized:
            logger.warning("DurableCacheAccounting already initialized")
            return
        self._engine = engine
        self._month_key = _current_month_key()

        try:
            await self._reserve_block()
            self._degraded = False
            self._initialized = True
            logger.info(
                "Durable cache accounting initialized month=%s neon_total=%d remaining=%d",
                self._month_key,
                self._neon_total,
                self._remaining,
            )
        except Exception:
            logger.warning(
                "Durable cache accounting initialization failed; "
                "quota telemetry degraded",
                exc_info=True,
            )
            self._degraded = True

        # Arm the background replenisher even when the initial reservation
        # failed so the process retries once Neon becomes available instead of
        # staying degraded for its whole lifetime.
        self._replenish_task = asyncio.create_task(
            self._background_replenish(),
            name="cache-accounting-replenish",
        )

    async def close(self) -> None:
        """Cancel the background replenishment task."""
        task = self._replenish_task
        self._replenish_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._initialized = False

    # -- Hot path ---------------------------------------------------------

    def record(self, count: int = 1) -> None:
        """Consume *count* locally reserved command slots.

        This method must never await and must never touch the network.  It
        is called on every Redis command from the synchronous hot path.

        Args:
            count: Number of provider commands being accounted for.
        """
        self._remaining = max(self._remaining - count, 0)

    # -- Read-only accessors ----------------------------------------------

    @property
    def initialized(self) -> bool:
        """Whether the accounting singleton has been successfully initialized."""
        return self._initialized

    @property
    def remaining(self) -> int:
        """Number of locally reserved command slots still available."""
        return self._remaining

    @property
    def neon_total(self) -> int | None:
        """Last-observed Neon aggregate, or ``None`` if never fetched."""
        return self._neon_total

    @property
    def degraded(self) -> bool:
        """Whether durable accounting is currently unreliable."""
        return self._degraded

    @property
    def month_key(self) -> str:
        """Current ``YYYY-MM`` accounting period."""
        return self._month_key

    def durable_total(self) -> int:
        """Return the month-to-date Neon aggregate.

        When Neon has never been reached the method falls back to zero so
        callers always get a non-negative integer.  A ``None`` total
        combined with ``degraded=True`` signals the health endpoint to
        report degraded status instead of a falsely low number.

        Returns:
            Non-negative aggregate command count from the Neon row.
        """
        neon = self._neon_total
        if neon is None:
            return 0
        return neon

    def snapshot(self) -> dict[str, int]:
        """Return a detached metrics snapshot.

        The snapshot mirrors the shape of
        :meth:`~app.cache_metrics.CacheCommandMetrics.snapshot` so the
        health endpoint can use it as a drop-in replacement for the
        process-local total.
        """
        total = self.durable_total()
        return {"durable_commands": total}

    # -- Neon block reservation -------------------------------------------

    async def _reserve_block(self) -> None:
        """Atomically reserve one block of commands from the Neon row."""
        engine = self._engine
        if engine is None:
            raise RuntimeError("DurableCacheAccounting engine not set")

        now = datetime.now(UTC)
        new_month = now.strftime("%Y-%m")
        if new_month != self._month_key:
            self._month_key = new_month

        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO cache_usage (month, commands) "
                    "VALUES (:month, :count) "
                    "ON CONFLICT (month) "
                    "DO UPDATE SET commands = cache_usage.commands + EXCLUDED.commands "
                    "RETURNING commands"
                ),
                {"month": self._month_key, "count": self._block_size},
            )
            row = result.fetchone()

        if row is None:
            raise RuntimeError("cache_usage RETURNING returned no row")

        total = int(row[0])
        if total < 0:
            raise ValueError(f"Unexpected negative cache_usage total: {total}")

        self._neon_total = total
        self._remaining += self._block_size
        self._reserved_total += self._block_size
        self._month_key = new_month

        logger.info(
            "Cache usage block reserved month=%s block=%d neon_total=%d remaining=%d",
            self._month_key,
            self._block_size,
            self._neon_total,
            self._remaining,
        )

    # -- Background replenishment -----------------------------------------

    async def _background_replenish(self) -> None:
        """Periodically reserve the next block before the current one runs out."""
        while True:
            try:
                await asyncio.sleep(self._replenish_interval)
            except asyncio.CancelledError:
                return

            month_key = _current_month_key()
            if month_key != self._month_key:
                self._month_key = month_key

            if self._remaining > self._low_water_mark:
                continue

            try:
                await self._reserve_block()
                self._initialized = True
                if self._degraded:
                    self._degraded = False
                    logger.info("Durable cache accounting recovered")
            except asyncio.CancelledError:
                return
            except Exception:
                logger.warning(
                    "Durable cache replenishment failed; quota telemetry degraded",
                    exc_info=True,
                )
                self._degraded = True


# Process-wide singleton --------------------------------------------------
cache_accounting = DurableCacheAccounting()
