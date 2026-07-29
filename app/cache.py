"""Redis/Upstash caching with circuit breaker and TTL tier support.

This module provides:
- TTL enum: SHORT, MEDIUM, LONG (values from config)
- CircuitBreaker: Simple circuit breaker for Redis resilience
- UpstashCache: Cache client (supports both Upstash cloud and local Redis)
- @cached decorator: Easy caching for async functions

Usage:
    from app.cache import cached, cache, TTL

    @cached(ttl=TTL.SHORT)
    async def get_roll_pool(user_id: int, db: AsyncSession):
        # Expensive DB query
        ...

    # Initialize at startup
    from app.config import get_redis_settings
    settings = get_redis_settings()
    if settings.is_configured:
        await cache.initialize(settings.upstash_redis_rest_url, settings.upstash_redis_rest_token)
    elif settings.redis_url:
        await cache.initialize(local_url=settings.redis_url)
"""

from __future__ import annotations

import enum
import functools
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, cast

import redis.asyncio as aioredis
from upstash_redis.asyncio import Redis as UpstashRedis

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Types to skip when generating cache keys (request objects, db sessions)
_SKIP_TYPES = frozenset({"AsyncSession", "Session", "Engine", "Request"})


class TTL(enum.Enum):
    """Cache TTL tiers - values are resolved from RedisSettings at runtime."""

    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


def _get_ttl_value(tier: TTL) -> int:
    """Get the actual TTL value in seconds for a tier."""
    # Import here to avoid circular imports
    from app.config import get_redis_settings

    settings = get_redis_settings()
    tier_map = {
        TTL.SHORT: settings.cache_ttl_short,
        TTL.MEDIUM: settings.cache_ttl_medium,
        TTL.LONG: settings.cache_ttl_long,
    }
    return tier_map[tier]


class CircuitState(enum.Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Simple circuit breaker for Redis resilience.

    Prevents cascading failures when Redis is unavailable.
    """

    def __init__(
        self,
        name: str = "redis",
        failure_threshold: int = 5,
        reset_timeout_seconds: int = 60,
    ) -> None:
        """Initialize the circuit breaker.

        Args:
            name: Name for logging/metrics
            failure_threshold: Number of failures before opening circuit
            reset_timeout_seconds: Seconds before attempting recovery
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout_seconds = reset_timeout_seconds
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state

    def can_attempt(self) -> bool:
        """Check if request should be allowed."""
        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.OPEN and self._opened_at:
            if time.time() - self._opened_at >= self.reset_timeout_seconds:
                logger.info("Circuit '%s': OPEN -> HALF_OPEN", self.name)
                self._state = CircuitState.HALF_OPEN
                return True
            return False

        return True

    def record_success(self) -> None:
        """Record successful request."""
        if self._state == CircuitState.HALF_OPEN:
            logger.info("Circuit '%s': HALF_OPEN -> CLOSED", self.name)
            self._state = CircuitState.CLOSED
            self._failure_count = 0

    def record_failure(self) -> None:
        """Record failed request."""
        self._failure_count += 1

        if self._state == CircuitState.HALF_OPEN:
            logger.warning("Circuit '%s': HALF_OPEN -> OPEN", self.name)
            self._state = CircuitState.OPEN
            self._opened_at = time.time()
        elif self._state == CircuitState.CLOSED:
            if self._failure_count >= self.failure_threshold:
                logger.warning(
                    "Circuit '%s': CLOSED -> OPEN (%d failures)",
                    self.name,
                    self._failure_count,
                )
                self._state = CircuitState.OPEN
                self._opened_at = time.time()


class UpstashCache:
    """Redis cache client with circuit breaker.

    Supports both Upstash cloud (via upstash-redis REST SDK) and local
    Redis (via redis-py). Provides graceful fallback when Redis is unavailable.
    """

    _instance: UpstashCache | None = None

    def __new__(cls) -> UpstashCache:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._client: Any = None
        self._circuit_breaker = CircuitBreaker(name="redis")
        self._initialized = False
        self._is_upstash = False

    @property
    def is_initialized(self) -> bool:
        return self._initialized and self._client is not None

    async def initialize(
        self,
        url: str | None = None,
        token: str | None = None,
        local_url: str | None = None,
    ) -> None:
        """Initialize Redis connection.

        Supports two modes:
        - Upstash cloud: provide url (REST URL) and token
        - Local Redis: provide local_url (e.g., redis://localhost:6379/0)
        """
        if self._initialized:
            logger.warning("Cache already initialized")
            return

        if local_url:
            try:
                self._client = aioredis.Redis.from_url(local_url, decode_responses=True)
                await self._client.ping()
                self._initialized = True
                self._is_upstash = False
                logger.info("Local Redis cache initialized: %s", local_url)
                return
            except Exception as e:
                logger.error("Failed to initialize local Redis: %s", e)
                self._client = None
                self._initialized = False
                return

        if url and token:
            try:
                self._client = UpstashRedis(url=url, token=token)
                await self._client.ping()
                self._initialized = True
                self._is_upstash = True
                logger.info("Upstash Redis cache initialized")
                return
            except Exception as e:
                logger.error("Failed to initialize Upstash Redis: %s", e)
                self._client = None
                self._initialized = False
                return

        logger.warning("No Redis configuration provided - caching disabled")

    async def close(self) -> None:
        """Close the Redis connection."""
        if self._client is not None:
            client = self._client
            self._client = None
            self._initialized = False
            if not self._is_upstash:
                await client.aclose()
            logger.info("Redis cache closed")

    async def get(self, key: str) -> Any | None:
        """Get a value from cache."""
        if not self.is_initialized or not self._circuit_breaker.can_attempt():
            return None

        if self._client is None:
            return None

        try:
            result = await self._client.get(key)
            self._circuit_breaker.record_success()
            if result is None:
                return None
            return json.loads(result)
        except Exception as e:
            self._circuit_breaker.record_failure()
            logger.warning("Cache get failed: %s", e)
            return None

    @staticmethod
    def _prepare_value(value: Any) -> Any:
        """Prepare a value for JSON serialization.

        Handles Pydantic models, SQLAlchemy models, sets, and other types.
        """
        if value is None:
            return None

        if isinstance(value, (str, int, float, bool)):
            return value

        if isinstance(value, set):
            return [UpstashCache._prepare_value(v) for v in value]

        if isinstance(value, dict):
            return {k: UpstashCache._prepare_value(v) for k, v in value.items()}

        if isinstance(value, list):
            return [UpstashCache._prepare_value(v) for v in value]

        if isinstance(value, tuple):
            return [UpstashCache._prepare_value(v) for v in value]

        # Pydantic v2 models
        if hasattr(value, "model_dump"):
            return UpstashCache._prepare_value(value.model_dump())

        # Pydantic v1 models / attrs
        if hasattr(value, "dict"):
            return UpstashCache._prepare_value(value.dict())

        # SQLAlchemy models: convert to dict via __dict__ but skip internal attrs
        if hasattr(value, "_sa_instance_state"):
            state = {c.key: getattr(value, c.key) for c in value.__table__.columns}
            return UpstashCache._prepare_value(state)

        # Datetime objects
        if hasattr(value, "isoformat"):
            return value.isoformat()

        return str(value)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Set a value in cache."""
        if not self.is_initialized or not self._circuit_breaker.can_attempt():
            return False

        if self._client is None:
            return False

        try:
            prepared = UpstashCache._prepare_value(value)
            data = json.dumps(
                prepared,
                default=str,
            )
            if ttl:
                await self._client.set(key, data, ex=ttl)
            else:
                await self._client.set(key, data)
            self._circuit_breaker.record_success()
            return True
        except Exception as e:
            self._circuit_breaker.record_failure()
            logger.warning("Cache set failed: %s", e)
            return False

    async def delete(self, key: str) -> bool:
        """Delete a value from cache."""
        if not self.is_initialized or not self._circuit_breaker.can_attempt():
            return False

        if self._client is None:
            return False

        try:
            await self._client.delete(key)
            self._circuit_breaker.record_success()
            return True
        except Exception as e:
            self._circuit_breaker.record_failure()
            logger.warning("Cache delete failed: %s", e)
            return False

    async def clear_pattern(self, pattern: str) -> int:
        """Clear all keys matching a pattern."""
        if not self.is_initialized or not self._circuit_breaker.can_attempt():
            return 0

        if self._client is None:
            return 0

        try:
            keys = await self._client.keys(pattern)
            if keys:
                deleted = await self._client.delete(*keys)
                self._circuit_breaker.record_success()
                return deleted
            return 0
        except Exception as e:
            self._circuit_breaker.record_failure()
            logger.warning("Cache clear_pattern failed: %s", e)
            return 0


# Global cache instance
cache = UpstashCache()


def _arg_to_cache_string(value: Any) -> str | None:
    """Convert an argument value to a stable cache key string.

    Returns None for types that should be skipped (e.g., db sessions, request objects).
    """
    if value is None:
        return "None"

    if isinstance(value, (str, int, float, bool)):
        return str(value)

    arg_type = value.__class__.__name__
    if arg_type in _SKIP_TYPES:
        return None

    # For model objects with an id attribute, use TypeName:id for stability
    if hasattr(value, "id") and not isinstance(value, type):
        return f"{arg_type}:{value.id}"

    return str(value)


def _generate_cache_key(func_name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    """Generate a cache key from function name and arguments."""
    key_parts: list[str] = [func_name]

    for arg in args:
        s = _arg_to_cache_string(arg)
        if s is not None:
            key_parts.append(s)

    for k, v in sorted(kwargs.items()):
        s = _arg_to_cache_string(v)
        if s is not None:
            key_parts.append(f"{k}={s}")

    key_str = ":".join(key_parts)
    if len(key_str) > 200:
        key_hash = hashlib.md5(key_str.encode()).hexdigest()
        return f"cache:{func_name}:{key_hash}"
    return f"cache:{key_str}"


def cached(
    ttl: int | TTL = TTL.MEDIUM,
    *,
    falsy_ttl: int | None = None,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator to cache async function results.

    Args:
        ttl: Time-to-live in seconds or TTL tier enum
        falsy_ttl: Optional different TTL for falsy results

    Usage:
        @cached(ttl=TTL.SHORT)
        async def get_roll_pool(user_id: int, db: AsyncSession):
            ...
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        # Resolve TTL enum to actual value
        actual_ttl = _get_ttl_value(ttl) if isinstance(ttl, TTL) else ttl

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            # Skip if cache not initialized
            if not cache.is_initialized:
                return await func(*args, **kwargs)

            cache_key = _generate_cache_key(getattr(func, "__name__", func.__class__.__name__), args, kwargs)

            # Try to get from cache
            cached_value = await cache.get(cache_key)
            if cached_value is not None:
                logger.debug("Cache hit: %s", cache_key)
                return cast(T, cached_value)

            # Execute function and cache result
            logger.debug("Cache miss: %s", cache_key)
            result = await func(*args, **kwargs)

            # Determine TTL for this result
            effective_ttl = actual_ttl
            if not result and falsy_ttl:
                effective_ttl = falsy_ttl

            if result:
                await cache.set(cache_key, result, ttl=effective_ttl)

            return result

        return cast(Callable[..., Awaitable[T]], wrapper)

    return decorator


async def invalidate_cache(pattern: str) -> int:
    """Invalidate cache keys matching a pattern.

    Args:
        pattern: Pattern to match (e.g., "cache:threads:*")

    Returns:
        Number of keys deleted
    """
    return await cache.clear_pattern(pattern)
