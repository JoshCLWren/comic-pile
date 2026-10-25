"""Low-overhead SQL-versus-other-wall timing for successful Roll requests.

This probe only observes existing per-request SQL counters and monotonic time.
It never starts a transaction, changes selection, or stores user-specific data.
"""

from __future__ import annotations

import logging
import time

from app.performance_diagnostics import get_request_diagnostics


class RollPhaseTrace:
    """Accumulate ordered Roll stage timings without additional database calls."""

    def __init__(self) -> None:
        """Snapshot the current monotonic clock and request-local SQL totals."""
        now = time.perf_counter()
        diagnostics = get_request_diagnostics()
        self._started_at = now
        self._last_wall = now
        self._started_sql = diagnostics.database_time_ms
        self._started_queries = diagnostics.database_queries
        self._last_sql = diagnostics.database_time_ms
        self._last_queries = diagnostics.database_queries
        self._phases: list[str] = []

    def mark(self, name: str) -> None:
        """Record one completed stage, distinguishing SQL and other wall time.

        Args:
            name: A fixed code-owned stage label, never a user-controlled value.
        """
        now = time.perf_counter()
        diagnostics = get_request_diagnostics()
        elapsed = max(0.0, (now - self._last_wall) * 1000)
        sql_ms = max(0.0, diagnostics.database_time_ms - self._last_sql)
        queries = max(0, diagnostics.database_queries - self._last_queries)
        self._phases.append(
            f"{name}:{elapsed:.2f}/{sql_ms:.2f}/{queries}"
        )
        self._last_wall = now
        self._last_sql = diagnostics.database_time_ms
        self._last_queries = diagnostics.database_queries

    def emit(self, logger: logging.Logger) -> None:
        """Emit one safe, compact summary with phase wall/SQL/query triplets.

        Args:
            logger: Existing Roll API logger.

        Notes:
            Non-SQL wall time is NOT CPU time: it includes async waiting,
            Python processing, fetching/hydration and framework overhead.
        """
        diagnostics = get_request_diagnostics()
        total_ms = (time.perf_counter() - self._started_at) * 1000
        sql_ms = max(0.0, diagnostics.database_time_ms - self._started_sql)
        queries = max(0, diagnostics.database_queries - self._started_queries)
        logger.info(
            "roll.phase_timing total_ms=%.2f sql_ms=%.2f non_sql_wall_ms=%.2f "
            "queries=%d stages=%s",
            total_ms,
            sql_ms,
            max(0.0, total_ms - sql_ms),
            queries,
            ",".join(self._phases),
        )
