"""Privacy-safe cache command-count instrumentation and flow budgets.

The recorder stores only normalized command-family names and aggregate counts. Cache
keys, user IDs, values, and provider credentials are never accepted by this API.
Production generation-cache operations share the same counter so tests and operators
observe the commands the application actually issues.
"""

from __future__ import annotations

from collections import Counter
from threading import Lock

from app.cache_generation import command_budget

UPSTASH_FREE_MONTHLY_COMMANDS = 500_000
CONSERVATIVE_MONTHLY_COMMAND_BUDGET = 350_000
MONTHLY_HEADROOM_COMMANDS = UPSTASH_FREE_MONTHLY_COMMANDS - CONSERVATIVE_MONTHLY_COMMAND_BUDGET

# Upper bounds for the cache-command composition of representative product flows.
# These are deliberately conservative cold-cache ceilings. A generation-scoped
# cached read costs at most two commands (atomic EVAL + SET) and a mutation
# invalidation costs one INCR.
CACHE_FLOW_COMMAND_CEILINGS: dict[str, int] = {
    "bootstrap": 4,
    "queue_load": 2,
    "roll": 5,
    "snooze": 1,
    "rating": 1,
    "thread_mutation": 1,
    "issue_mutation": 1,
    "continuity_mutation": 1,
}


class CacheCommandMetrics:
    """Track aggregate cache command counts without recording command payloads."""

    def __init__(self, counts: Counter[str] | None = None) -> None:
        """Initialize a recorder, optionally sharing an existing aggregate counter.

        Args:
            counts: Existing command counter to expose through this privacy-safe API.
        """
        self._counts = counts if counts is not None else Counter()
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

    def assert_within_flow_ceiling(self, flow: str) -> None:
        """Raise when the current aggregate count exceeds a named flow ceiling.

        Args:
            flow: Key from :data:`CACHE_FLOW_COMMAND_CEILINGS`.

        Raises:
            KeyError: If ``flow`` has no documented ceiling.
            AssertionError: If recorded commands exceed the ceiling.
        """
        ceiling = CACHE_FLOW_COMMAND_CEILINGS[flow]
        total = self.total()
        if total > ceiling:
            raise AssertionError(f"{flow} used {total} cache commands; ceiling is {ceiling}")


# ``command_budget`` is the production generation-cache instrumentation introduced
# with bounded invalidation. Sharing its Counter makes this the stable public metrics
# surface without adding keys, values, or user identifiers to instrumentation.
cache_command_metrics = CacheCommandMetrics(command_budget.counts)
