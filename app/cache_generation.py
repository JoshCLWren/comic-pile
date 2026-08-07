"""Bounded user-scoped cache generation primitives.

The remote cache can be invalidated without scanning Redis by storing one generation
counter per user. Cached values include the current generation in their key, and a
mutation invalidates every prior value for that user with one ``INCR`` command.
"""

from __future__ import annotations

import functools
import inspect
import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar, cast

from app.cache import TTL, _generate_cache_key, _get_ttl_value, cache

logger = logging.getLogger(__name__)

T = TypeVar("T")

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
    command_budget.record("generation_get")
    raw_generation = await client.get(generation_key(user_id))
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
    command_budget.record("generation_incr")
    raw_generation = await client.incr(generation_key(user_id))
    try:
        generation = int(raw_generation)
    except (TypeError, ValueError) as exc:
        raise ValueError("Cache generation must be an integer") from exc
    if generation <= 0:
        raise ValueError("Incremented cache generation must be positive")
    return generation


async def invalidate_user_cache(user_id: int) -> bool:
    """Invalidate every generation-scoped cached value for one user.

    The production entrypoint is deliberately a no-op while remote caching is
    disabled. When caching is configured, one successful call performs exactly one
    Redis ``INCR`` through :func:`bump_user_generation`; old value keys expire by
    TTL and are never scanned or deleted individually.

    Args:
        user_id: Authenticated user identifier whose cached views became stale.

    Returns:
        ``True`` when the generation was bumped, otherwise ``False`` when caching
        is unavailable or the cache command fails.
    """
    if not cache.is_initialized or cache._client is None:
        return False

    try:
        await bump_user_generation(cache._client, user_id)
    except Exception as exc:
        logger.warning("Cache generation invalidation failed: %s", exc)
        return False
    return True


async def invalidate_user_caches(user_ids: Iterable[int]) -> int:
    """Invalidate each distinct user namespace at most once.

    Mutation helpers can overlap in the logical cache families they invalidate.
    Collapsing user IDs before issuing generation bumps prevents nested helpers from
    multiplying remote commands while preserving cross-user correctness.

    Args:
        user_ids: User identifiers whose cached views became stale.

    Returns:
        Number of user namespaces successfully invalidated.
    """
    distinct_user_ids = sorted(set(user_ids))
    if not distinct_user_ids or not cache.is_initialized or cache._client is None:
        return 0

    invalidated = 0
    for user_id in distinct_user_ids:
        if user_id <= 0:
            raise ValueError("user_id must be positive")
        try:
            await bump_user_generation(cache._client, user_id)
        except Exception as exc:
            logger.warning("Cache generation invalidation failed: %s", exc)
            continue
        invalidated += 1
    return invalidated


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


def generation_cached(
    ttl: int | TTL = TTL.MEDIUM,
    *,
    falsy_ttl: int | None = None,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Cache a user-scoped async function behind one generation lookup.

    The decorator deliberately bypasses caching when it cannot resolve a positive
    user identifier. That keeps ownership explicit and prevents a supposedly
    user-scoped cache entry from falling back to a shared key.

    A cache hit costs at most two remote commands: one generation ``GET`` and one
    value ``GET``. A cache miss that is stored costs at most three: generation
    ``GET``, value ``GET``, and value ``SET``.

    Cache failures are fail-open: if the generation lookup fails, the wrapped
    database read still executes instead of turning optional Redis into a request
    dependency.

    Args:
        ttl: Time-to-live in seconds or a configured TTL tier.
        falsy_ttl: Optional alternate TTL for falsy results.

    Returns:
        Decorator for an async cached function.
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        actual_ttl = _get_ttl_value(ttl) if isinstance(ttl, TTL) else ttl
        signature = inspect.signature(func)

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            if not cache.is_initialized:
                return await func(*args, **kwargs)

            try:
                bound = signature.bind_partial(*args, **kwargs)
            except TypeError:
                return await func(*args, **kwargs)

            user_id = user_id_from_arguments(dict(bound.arguments))
            if user_id is None:
                return await func(*args, **kwargs)

            client = cache._client
            if client is None:
                return await func(*args, **kwargs)

            try:
                generation = await get_user_generation(client, user_id)
            except Exception as exc:
                logger.warning("Cache generation read failed: %s", exc)
                return await func(*args, **kwargs)

            func_name = getattr(func, "__name__", func.__class__.__name__)
            logical_key = _generate_cache_key(func_name, func, args, kwargs)
            cache_key = namespaced_cache_key(user_id, generation, logical_key)

            command_budget.record("value_get")
            cached_value = await cache.get(cache_key)
            if cached_value is not None:
                return cast(T, cached_value)

            result = await func(*args, **kwargs)
            effective_ttl = falsy_ttl if falsy_ttl is not None and not result else actual_ttl
            if result or falsy_ttl is not None:
                command_budget.record("value_set")
                await cache.set(cache_key, result, ttl=effective_ttl)
            return result

        return cast(Callable[..., Awaitable[T]], wrapper)

    return decorator