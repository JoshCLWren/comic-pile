"""Bounded user-scoped cache generation primitives.

The remote cache can be invalidated without scanning Redis by storing one generation
counter per user. Cached values include the current generation in their key, and a
mutation invalidates every prior value for that user with one ``INCR`` command.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_GENERATION_PREFIX = "cache:generation:user"
_VALUE_PREFIX = "cache:user"


class GenerationCacheClient(Protocol):
    """Minimal async Redis contract used by generation operations."""

    def get(self, key: str) -> Awaitable[str | int | None]:
        """Return a generation counter value."""
        ...

    def incr(self, key: str) -> Awaitable[int]:
        """Increment and return a generation counter value."""
        ...


@dataclass(slots=True)
class CacheCommandBudget:
    """Track cache command counts without recording keys or user data."""

    counts: Counter[str] = field(default_factory=Counter)

    def record(self, command: str, count: int = 1) -> None:
        """Record cache commands for bounded-budget diagnostics.

        Args:
            command: Logical cache command name such as ``get`` or ``invalidate``.
            count: Number of commands represented by this operation.

        Raises:
            ValueError: If ``count`` is negative.
        """
        if count < 0:
            raise ValueError("Cache command count cannot be negative")
        self.counts[command] += count
        logger.debug("cache_command command=%s count=%d", command, count)

    @property
    def total(self) -> int:
        """Return the total recorded command count."""
        return sum(self.counts.values())


command_budget = CacheCommandBudget()


def generation_key(user_id: int) -> str:
    """Return the deterministic generation-counter key for a user.

    Args:
        user_id: Authenticated user identifier.

    Returns:
        Redis key containing only the numeric user identifier.

    Raises:
        ValueError: If ``user_id`` is not positive.
    """
    if user_id <= 0:
        raise ValueError("user_id must be positive")
    return f"{_GENERATION_PREFIX}:{user_id}"


def namespaced_cache_key(user_id: int, generation: int, logical_key: str) -> str:
    """Build a user-scoped cache key for one generation.

    Args:
        user_id: Authenticated user identifier.
        generation: Current user cache generation.
        logical_key: Existing logical cache key.

    Returns:
        User- and generation-scoped cache key.

    Raises:
        ValueError: If identifiers are invalid or the logical key is empty.
    """
    if user_id <= 0:
        raise ValueError("user_id must be positive")
    if generation < 0:
        raise ValueError("generation cannot be negative")
    if not logical_key:
        raise ValueError("logical_key cannot be empty")

    normalized = logical_key.removeprefix("cache:")
    return f"{_VALUE_PREFIX}:{user_id}:g{generation}:{normalized}"


async def get_user_generation(client: GenerationCacheClient, user_id: int) -> int:
    """Read one user's current cache generation with exactly one cache command.

    A missing generation means the user has never invalidated a generation-scoped
    value, so generation zero is valid without an initialization write.

    Args:
        client: Async Redis-compatible generation client.
        user_id: Authenticated user identifier.

    Returns:
        Current non-negative generation, defaulting to zero when no counter exists.

    Raises:
        ValueError: If Redis returns an invalid generation value.
    """
    raw_generation = await client.get(generation_key(user_id))
    command_budget.record("generation_get")
    if raw_generation is None:
        return 0

    try:
        generation = int(raw_generation)
    except (TypeError, ValueError) as exc:
        raise ValueError("Cache generation must be an integer") from exc
    if generation < 0:
        raise ValueError("Cache generation cannot be negative")
    return generation


async def bump_user_generation(client: GenerationCacheClient, user_id: int) -> int:
    """Invalidate all cached values for one user with exactly one cache command.

    Existing value keys are left to expire naturally. Incrementing the generation
    makes them unreachable immediately across every application instance without a
    wildcard scan, key inventory, or repeated logical-family deletion.

    Args:
        client: Async Redis-compatible generation client.
        user_id: Authenticated user identifier.

    Returns:
        Newly active positive generation.

    Raises:
        ValueError: If Redis returns an invalid generation value.
    """
    raw_generation = await client.incr(generation_key(user_id))
    command_budget.record("generation_incr")
    try:
        generation = int(raw_generation)
    except (TypeError, ValueError) as exc:
        raise ValueError("Cache generation must be an integer") from exc
    if generation <= 0:
        raise ValueError("Incremented cache generation must be positive")
    return generation


def user_id_from_arguments(arguments: dict[str, Any]) -> int | None:
    """Extract a user identifier from bound cached-function arguments.

    Cached functions currently receive ownership either as an explicit ``user_id``
    integer or as a user model-like object. Keeping this resolution in one place
    lets the decorator add user-scoped generations without logging or serializing
    the user object.

    Args:
        arguments: Arguments produced by ``inspect.Signature.bind_partial``.

    Returns:
        Positive user identifier when one can be resolved, otherwise ``None``.
    """
    explicit_user_id = arguments.get("user_id")
    if isinstance(explicit_user_id, int) and explicit_user_id > 0:
        return explicit_user_id

    for name in ("user", "current_user"):
        user = arguments.get(name)
        candidate = getattr(user, "id", None)
        if isinstance(candidate, int) and candidate > 0:
            return candidate
    return None
