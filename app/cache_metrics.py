"""Privacy-safe cache command-count instrumentation.

The recorder intentionally stores only command names and aggregate counts. Cache
keys, user ids, values, and provider credentials are never accepted by the API,
which keeps operational command-budget metrics free of user data.
"""

from __future__ import annotations

from collections import Counter
from threading import Lock


class CacheCommandMetrics:
    """Track aggregate cache command counts without recording command payloads."""

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()
        self._lock = Lock()

    def record(self, command: str, *, count: int = 1) -> None:
        """Record one or more provider-billed cache commands.

        Args:
            command: Stable command family such as ``get``, ``set``, or ``delete``.
            count: Number of provider commands represented by this operation.

        Raises:
            ValueError: If the command is empty or count is not positive.
        """
        normalized = command.strip().lower()
        if not normalized:
            raise ValueError("cache metric command must not be empty")
        if count <= 0:
            raise ValueError("cache metric count must be positive")

        with self._lock:
            self._counts[normalized] += count

    def snapshot(self) -> dict[str, int]:
        """Return a detached command-count snapshot suitable for metrics/tests."""
        with self._lock:
            return dict(self._counts)

    def total(self) -> int:
        """Return the total recorded provider command count."""
        with self._lock:
            return sum(self._counts.values())

    def reset(self) -> None:
        """Clear counters, primarily for deterministic tests."""
        with self._lock:
            self._counts.clear()


cache_command_metrics = CacheCommandMetrics()
