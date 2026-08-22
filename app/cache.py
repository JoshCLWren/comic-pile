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

    # Configure at startup without opening a network connection. The first
    # real cache command performs the connection lazily.
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
import inspect
import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any, ParamSpec, TypeVar, cast

import asyncpg
import redis.asyncio as aioredis
from sqlalchemy import Column, DateTime, Integer, String, Table, create_engine, event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from upstash_redis.asyncio import Redis as UpstashRedis

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")

# Types to skip when generating cache keys (request objects, db sessions)
_SKIP_TYPES = frozenset({"AsyncSession", "Session", "Engine", "Request"})
_CONNECT_TIMEOUT_SECONDS = 5.0


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
    """Simple circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Simple circuit breaker states.

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

    def reset(self) -> None:
        """Reset the circuit after a confirmed healthy connection."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at = None

    def record_success(self) -> None:
        """Record successful request."""
        if self._state == CircuitState.HALF_OPEN:
            logger.info("Circuit '%s': HALF_OPEN -> CLOSED", self.name)
            self.reset()
        elif self._state == CircuitState.CLOSED:
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
        elif self._state == CircuitState.CLOSED:
            if self._failure_count >= self.failure_threshold:
                logger.warning(
                    "Circuit '%s': CLOSED -> OPEN (%d failures)",
                    self.name,
                    self._failure_count,
                )
                self._state = CircuitState.OPEN
                self._opened_at = time.time()


_cache_table = Table(
    "comic_pile_cache",
    Column("key", String(512), primary_key=True),
    Column("value", String, nullable=False),
    Column("created_at", DateTime, default=datetime.utcnow, nullable=False),
)


class PostgresCacheClient:
    """PostgreSQL-backed cache client using asyncpg.

    Provides get/set/delete operations backed by PostgreSQL table storage.
    Implements the same interface as UpstashCache but stores data in PostgreSQL
    for fail-open behavior when Redis is unavailable.
    """

    _instance: PostgresCacheClient | None = None
    _engine: AsyncEngine | None = None
    _session_maker: async_sessionmaker | None = None

    def __new__(cls) -> PostgresCacheClient:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._pool: asyncpg.Connection | None = None
        self._circuit_breaker = CircuitBreaker(name="postgres_cache")
        self._initialized = False
        self._url: str | None = None

    @classmethod
    async def _create_schema(cls) -> None:
        """Create the cache table if it doesn't exist."""
        if cls._engine is None:
            return
        from sqlalchemy import text as sa_text

        async with cls._engine.begin() as conn:
            await conn.execute(
                sa_text(
                    "CREATE TABLE IF NOT EXISTS comic_pile_cache ("
                    "key VARCHAR(512) PRIMARY KEY, "
                    "value TEXT NOT NULL, "
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                    ")"
                )
            )
            await conn.execute(
                sa_text(
                    "CREATE INDEX IF NOT EXISTS idx_cache_created_at "
                    "ON comic_pile_cache (created_at)"
                )
            )

    @property
    def is_initialized(self) -> bool:
        return self._initialized and self._pool is not None

    async def initialize(self, url: str) -> None:
        """Initialize the PostgreSQL connection pool.

        Args:
            url: PostgreSQL connection URL.
        """
        if self._initialized:
            logger.warning("PostgresCache already initialized")
            return

        self._url = url
        try:
            self._pool = await asyncpg.connect(url, command_timeout=5.0)
            self._circuit_breaker.reset()
            self._initialized = True
            logger.info("PostgreSQL cache configured for lazy connection")

            if cls._engine is None:
                cls._engine = create_async_engine(url, echo=False)
                await cls._create_schema()
        except Exception as e:
            logger.warning("Failed to initialize PostgreSQL cache: %s", e)
            self._pool = None
            self._initialized = False

    async def close(self) -> None:
        """Close the PostgreSQL connection."""
        if self._pool is not None:
            await self._pool.close()
        self._pool = None
        self._initialized = False
        logger.info("PostgreSQL cache connection closed")

    @staticmethod
    def _reconstruct_value(value: str) -> Any:
        """Reconstruct a value from serialized JSON."""
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return json.loads(value)

    @staticmethod
    def _prepare_value(value: Any) -> str:
        """Prepare a value for storage."""
        if isinstance(value, (str, int, float, bool)):
            return json.dumps(value)
        if hasattr(value, "model_dump"):
            return json.dumps(value.model_dump())
        if hasattr(value, "dict"):
            return json.dumps(value.dict())
        return json.dumps(value)

    async def get(self, key: str) -> Any | None:
        """Get a value from cache."""
        if not self.is_initialized or not self._circuit_breaker.can_attempt():
            return None

        if self._pool is None:
            return None

        try:
            row = await self._pool.fetchrow(
                "SELECT value FROM comic_pile_cache WHERE key = $1", key
            )
            self._circuit_breaker.record_success()
            if row is None:
                return None
            return PostgresCacheClient._reconstruct_value(row["value"])
        except Exception as e:
            self._circuit_breaker.record_failure()
            logger.warning("Cache get failed: %s", e)
            return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Set a value in cache."""
        if not self.is_initialized or not self._circuit_breaker.can_attempt():
            return False

        if self._pool is None:
            return False

        try:
            serialized = PostgresCacheClient._prepare_value(value)
            now = datetime.utcnow()
            await self._pool.execute(
                """
                INSERT INTO comic_pile_cache (key, value, created_at)
                VALUES ($1, $2, $3)
                ON CONFLICT (key) DO UPDATE SET value = $2, created_at = $3
                """,
                key,
                serialized,
                now,
            )
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

        if self._pool is None:
            return False

        try:
            await self._pool.execute(
                "DELETE FROM comic_pile_cache WHERE key = $1", key
            )
            self._circuit_breaker.record_success()
            return True
        except Exception as e:
            self._circuit_breaker.record_failure()
            logger.warning("Cache delete failed: %s", e)
            return False

    async def incr(self, key: str) -> int:
        """Increment and return a generation counter value."""
        if not self.is_initialized or not self._circuit_breaker.can_attempt():
            return 1

        if self._pool is None:
            return 1

        try:
            row = await self._pool.fetchrow(
                """
                INSERT INTO comic_pile_cache (key, value, created_at)
                VALUES ($1, '0', CURRENT_TIMESTAMP)
                ON CONFLICT (key) DO UPDATE SET value = (value::int + 1)::text
                RETURNING value
                """,
                key,
            )
            self._circuit_breaker.record_success()
            return int(row["value"]) if row else 1
        except Exception as e:
            self._circuit_breaker.record_failure()
            logger.warning("Cache incr failed: %s", e)
            return 1

    async def eval(self, script: str, keys: list[str], args: list[str]) -> list[object | None]:
        """Evaluate a Lua script (no-op for PostgreSQL - returns None for compatibility)."""
        logger.warning("eval command not supported in PostgresCacheClient")
        return [None, None]

    async def clear_pattern(self, pattern: str) -> int:
        """Clear all keys matching a pattern."""
        if not self.is_initialized or not self._circuit_breaker.can_attempt():
            return 0

        try:
            result = await self._pool.fetch(
                "SELECT key FROM comic_pile_cache WHERE key LIKE $1", pattern
            )
            keys = [row["key"] for row in result]
            for key in keys:
                await self._pool.execute("DELETE FROM comic_pile_cache WHERE key = $1", key)
            self._circuit_breaker.record_success()
            return len(keys)
        except Exception as e:
            self._circuit_breaker.record_failure()
            logger.warning("Cache clear_pattern failed: %s", e)
            return 0


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
        """Configure a Redis client without opening a network connection.

        Startup must remain independent from optional cache availability. Client
        construction is local; the first real cache command performs the network
        connection and is protected by the command-level failure handling.

        Supports two modes:
        - Upstash cloud: provide url (REST URL) and token
        - Local Redis: provide local_url (e.g., redis://localhost:6379/0)
        """
        if self._initialized:
            logger.warning("Cache already initialized")
            return

        if local_url:
            self._client = aioredis.Redis.from_url(
                local_url,
                decode_responses=True,
                socket_connect_timeout=_CONNECT_TIMEOUT_SECONDS,
                socket_timeout=_CONNECT_TIMEOUT_SECONDS,
            )
            self._circuit_breaker.reset()
            self._initialized = True
            self._is_upstash = False
            logger.info("Local Redis cache configured for lazy connection")
            return

        if url and token:
            self._client = UpstashRedis(url=url, token=token)
            self._circuit_breaker.reset()
            self._initialized = True
            self._is_upstash = True
            logger.info("Upstash Redis cache configured for lazy connection")
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

    @staticmethod
    def _reconstruct_value(value: Any) -> Any:
        """Reconstruct a value from deserialized JSON, restoring tagged types."""
        if isinstance(value, dict) and "__type__" in value:
            type_tag = value["__type__"]
            if type_tag == "set":
                return {UpstashCache._reconstruct_value(v) for v in value["values"]}
        if isinstance(value, dict):
            return {k: UpstashCache._reconstruct_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [UpstashCache._reconstruct_value(v) for v in value]
        return value

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
            return UpstashCache._reconstruct_value(json.loads(result))
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
            return {"__type__": "set", "values": [UpstashCache._prepare_value(v) for v in value]}

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
            if ttl is not None and ttl <= 0:
                await self._client.delete(key)
            elif ttl is not None:
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
        """Clear all keys matching a pattern using SCAN (non-blocking)."""
        if not self.is_initialized or not self._circuit_breaker.can_attempt():
            return 0

        if self._client is None:
            return 0

        try:
            deleted = 0
            cursor = 0
            batch_size = 100

            while True:
                cursor, keys = await self._client.scan(
                    cursor=cursor, match=pattern, count=batch_size
                )
                if keys:
                    await self._client.delete(*keys)
                    deleted += len(keys)
                if cursor == 0:
                    break

            self._circuit_breaker.record_success()
            return deleted
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


def _generate_cache_key(
    func_name: str,
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> str:
    """Generate a cache key from function name and arguments.

    Uses inspect.signature to bind arguments in declaration order,
    producing stable keys regardless of whether callers use positional
    or keyword arguments.
    """
    key_parts: list[str] = [func_name]

    try:
        sig = inspect.signature(func)
        bound = sig.bind_partial(*args, **kwargs)
        bound.apply_defaults()

        for _, value in bound.arguments.items():
            s = _arg_to_cache_string(value)
            if s is not None:
                key_parts.append(s)
    except (TypeError, ValueError):
        # Fallback: process args positionally, then kwargs sorted
        for arg in args:
            s = _arg_to_cache_string(arg)
            if s is not None:
                key_parts.append(s)
        for k, v in sorted(kwargs.items()):
            s = _arg_to_cache_string(v)
            if s is not None:
                key_parts.append(f"{k}={v}")

    key_str = ":".join(key_parts) + ":"
    if len(key_str) > 200:
        key_hash = hashlib.md5(key_str.encode()).hexdigest()
        return f"cache:{func_name}:{key_hash}:"
    return f"cache:{key_str}"


def _has_user_cache_scope(
    func: Callable[..., object],
    *args: object,
    **kwargs: object,
) -> bool:
    """Return whether a cached call carries an explicit positive user identity."""
    try:
        bound = inspect.signature(func).bind_partial(*args, **kwargs)
    except (TypeError, ValueError):
        return False

    explicit_user_id = bound.arguments.get("user_id")
    if isinstance(explicit_user_id, int) and explicit_user_id > 0:
        return True

    for name in ("user", "current_user"):
        user = bound.arguments.get(name)
        candidate = getattr(user, "id", None)
        if isinstance(candidate, int) and candidate > 0:
            return True
    return False


def cached(
    ttl: int | TTL = TTL.MEDIUM,
    *,
    falsy_ttl: int | None = None,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Decorator to cache async function results.

    User-scoped calls are routed through the bounded generation namespace so
    mutations can invalidate every cached view for one user with one generation
    bump. Calls without a resolvable user identity retain the legacy key behavior.

    Args:
        ttl: Time-to-live in seconds or TTL tier enum
        falsy_ttl: Optional different TTL for falsy results

    Returns:
        A decorator preserving the wrapped async function's parameter and return types.

    Usage:
        @cached(ttl=TTL.SHORT)
        async def get_roll_pool(user_id: int, db: AsyncSession):
            ...
    """

    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        # Resolve TTL enum to actual value
        actual_ttl = _get_ttl_value(ttl) if isinstance(ttl, TTL) else ttl
        generation_wrapper: Callable[P, Awaitable[T]] | None = None

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            nonlocal generation_wrapper

            if _has_user_cache_scope(func, *args, **kwargs):
                if generation_wrapper is None:
                    # Lazy import avoids a module cycle: cache_generation imports
                    # this module's cache primitives to implement the namespace.
                    from app.cache_generation import generation_cached

                    generation_wrapper = generation_cached(
                        ttl,
                        falsy_ttl=falsy_ttl,
                    )(func)
                return await generation_wrapper(*args, **kwargs)

            # Skip if cache not initialized
            if not cache.is_initialized:
                return await func(*args, **kwargs)

            func_name = getattr(func, "__name__", func.__class__.__name__)
            cache_key = _generate_cache_key(func_name, func, args, kwargs)

            # Try to get from cache
            cached_value = await cache.get(cache_key)
            if cached_value is not None:
                logger.debug("Cache hit: %s", cache_key)
                return cast(T, cached_value)

            # Execute function and cache result
            logger.debug("Cache miss: %s", cache_key)
            result = await func(*args, **kwargs)

            # Determine TTL for this result
            effective_ttl = falsy_ttl if falsy_ttl is not None and not result else actual_ttl

            if result or falsy_ttl is not None:
                await cache.set(cache_key, result, ttl=effective_ttl)

            return result

        return wrapper

    return decorator


async def invalidate_cache(pattern: str) -> int:
    """Invalidate cache keys matching a pattern.

    Args:
        pattern: Pattern to match (e.g., "cache:threads:*")

    Returns:
        Number of keys deleted
    """
    return await cache.clear_pattern(pattern)