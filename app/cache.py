"""Cache provider abstraction with circuit breaker and TTL tier support.

This module provides:
- TTL enum: SHORT, MEDIUM, LONG (values from config)
- CircuitBreaker: Simple circuit breaker for cache resilience (fail-open demotion)
- BaseCache: Abstract base class for cache providers
- UpstashCache: Redis cache client (Upstash cloud or local Redis), extends BaseCache
- PostgresCache: Postgres-backed cache client, extends BaseCache
- @cached decorator: Easy caching for async functions

Usage:
    from app.cache import cached, cache, TTL

    @cached(ttl=TTL.SHORT)
    async def get_roll_pool(user_id: int, db: AsyncSession):
        # Expensive DB query
        ...

Cache provider is selected at startup via CACHE_PROVIDER setting (postgres|redis|off).
"""

from __future__ import annotations

import abc
import enum
import functools
import hashlib
import inspect
import json
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, ParamSpec, TypeVar, cast

import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from upstash_redis.asyncio import Redis as UpstashRedis

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")

_SKIP_TYPES = frozenset({"AsyncSession", "Session", "Engine", "Request"})
_CONNECT_TIMEOUT_SECONDS = 5.0


class TTL(enum.Enum):
    """Cache TTL tiers - values are resolved from RedisSettings at runtime."""

    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


def _get_ttl_value(tier: TTL) -> int:
    """Get the actual TTL value in seconds for a tier."""
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

    Prevents cascading failures when the cache provider is unavailable.
    Once opened, the circuit stays open for the process lifetime (fail-open
    demotion policy): the reset_timeout_seconds parameter is retained for
    interface compatibility but the demotion state is permanent.
    """

    def __init__(
        self,
        name: str = "cache",
        failure_threshold: int = 5,
        reset_timeout_seconds: int = 60,
    ) -> None:
        """Initialize the circuit breaker.

        Args:
            name: Name for logging/metrics.
            failure_threshold: Number of failures before opening circuit.
            reset_timeout_seconds: Retention parameter for interface compatibility.
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
        """Check if a request should be allowed."""
        if self._state == CircuitState.CLOSED:
            return True
        return False

    def reset(self) -> None:
        """Reset the circuit after a confirmed healthy connection."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at = None

    def record_success(self) -> None:
        """Record successful request."""
        if self._state == CircuitState.CLOSED:
            self._failure_count = 0

    def record_failure(self) -> None:
        """Record failed request."""
        self._failure_count += 1
        if self._state == CircuitState.CLOSED and self._failure_count >= self.failure_threshold:
            logger.warning(
                "Circuit %s: CLOSED -> OPEN (%d failures)",
                self.name,
                self._failure_count,
            )
            self._state = CircuitState.OPEN
            self._opened_at = time.time()


class BaseCache(abc.ABC):
    """Abstract base class for all cache providers.

    Subclasses implement the remote storage operations.  The active provider
    instance is exposed via the module-level ``cache`` singleton.
    """

    def __init__(self) -> None:
        self._initialized: bool = False
        self._circuit_breaker = CircuitBreaker()

    @property
    def is_initialized(self) -> bool:
        """Return True when this provider has finished startup configuration."""
        return self._initialized

    @abc.abstractmethod
    async def initialize(self, *args: Any, **kwargs: Any) -> None:
        """Configure this provider without opening a network connection."""

    @abc.abstractmethod
    async def close(self) -> None:
        """Release resources held by this provider."""

    @abc.abstractmethod
    async def get(self, key: str) -> Any | None:
        """Return the cached value for key, or None."""

    @abc.abstractmethod
    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Store value under key; return whether the write succeeded."""

    @abc.abstractmethod
    async def delete(self, key: str) -> bool:
        """Remove key; return whether the delete succeeded."""

    @abc.abstractmethod
    async def clear_pattern(self, pattern: str) -> int:
        """Remove every key matching pattern; return the deletion count."""


class UpstashCache(BaseCache):
    """Redis cache client with circuit breaker.

    Supports both Upstash cloud (via upstash-redis REST SDK) and local
    Redis (via redis-py).  Provides graceful fallback when Redis is unavailable.
    """

    _instance: UpstashCache | None = None

    def __new__(cls) -> UpstashCache:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if hasattr(self, "_initialized") and self._initialized and hasattr(self, "_client"):
            return
        super().__init__()
        self._client: Any = None
        self._initialized = False

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
            logger.info("Local Redis cache configured for lazy connection")
            return

        if url and token:
            self._client = UpstashRedis(url=url, token=token)
            self._circuit_breaker.reset()
            self._initialized = True
            logger.info("Upstash Redis cache configured for lazy connection")
            return

        logger.warning("No Redis configuration provided - caching disabled")

    async def close(self) -> None:
        """Close the Redis connection."""
        if self._client is not None:
            client = self._client
            self._client = None
            self._initialized = False
            if hasattr(client, "aclose"):
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
        if not self._circuit_breaker.can_attempt() or self._client is None:
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
        if hasattr(value, "model_dump"):
            return UpstashCache._prepare_value(value.model_dump())
        if hasattr(value, "dict"):
            return UpstashCache._prepare_value(value.dict())
        if hasattr(value, "_sa_instance_state"):
            state = {c.key: getattr(value, c.key) for c in value.__table__.columns}
            return UpstashCache._prepare_value(state)
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Set a value in cache."""
        if not self._circuit_breaker.can_attempt() or self._client is None:
            return False

        try:
            prepared = UpstashCache._prepare_value(value)
            data = json.dumps(prepared, default=str)
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
        if not self._circuit_breaker.can_attempt() or self._client is None:
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
        if not self._circuit_breaker.can_attempt() or self._client is None:
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

    async def get_generation(self, key: str) -> str | int | None:
        """Return the cached value for a generation-counter key (Redis interface)."""
        if not self._circuit_breaker.can_attempt() or self._client is None:
            return None
        try:
            result = await self._client.get(key)
            self._circuit_breaker.record_success()
            return result
        except Exception as e:
            self._circuit_breaker.record_failure()
            logger.warning("Cache get_generation failed: %s", e)
            return None

    async def incr_generation(self, key: str) -> int:
        """Atomically increment a generation counter and return the new value."""
        if not self._circuit_breaker.can_attempt() or self._client is None:
            raise RuntimeError("Cache client is unavailable for incr")
        try:
            result = await self._client.incr(key)
            self._circuit_breaker.record_success()
            return int(result)
        except Exception as e:
            self._circuit_breaker.record_failure()
            logger.warning("Cache incr_generation failed: %s", e)
            raise


class PostgresCache(BaseCache):
    """Postgres-backed cache implementation.

    Provides the same GenerationCacheClient interface (get, incr) as the
    Redis backends, enabling transparent use from ``cache_generation``.
    Values are serialized to JSONB in the cache_entries table; generation
    counters live in the cache_generations table.
    """

    def __init__(self) -> None:
        super().__init__()
        self._engine: Any = None
        self._sessionmaker: Any = None

    @property
    def is_initialized(self) -> bool:
        return self._initialized and self._sessionmaker is not None

    async def initialize(self, database_url: str) -> None:
        """Configure the Postgres cache backend from a database URL.

        Opens a connection-pooled async engine and a session factory.  No
        database round-trip occurs at this stage; the first cache command
        lazily acquires a connection.
        """
        if self._initialized:
            logger.warning("Postgres cache already initialized")
            return

        try:
            self._engine = create_async_engine(
                database_url,
                pool_pre_ping=True,
                pool_size=3,
                max_overflow=5,
                pool_recycle=300,
                connect_args={
                    "timeout": _CONNECT_TIMEOUT_SECONDS,
                    "server_settings": {
                        "application_name": "comic_pile_cache",
                    },
                },
                pool_reset_on_return="rollback",
            )

            async def _noop_timeout(seconds: float) -> AsyncIterator[None]:
                """No-op async context manager; placeholder for timeout instrumentation."""
                yield

            self._sessionmaker = async_sessionmaker(
                self._engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
                autocommit=False,
            )

            async with self._sessionmaker() as session:
                await session.execute(text("SELECT 1"))
                await session.commit()

            self._circuit_breaker.reset()
            self._initialized = True
            logger.info("Postgres cache initialized for database: %s", database_url)
        except Exception as exc:
            logger.error("Postgres cache initialization failed: %s", exc)
            self._engine = None
            self._sessionmaker = None
            self._initialized = False
            raise

    async def close(self) -> None:
        """Close the database engine used by the Postgres cache."""
        if self._engine is not None:
            try:
                await self._engine.dispose()
            except Exception as exc:
                logger.warning("Postgres cache engine dispose failed: %s", exc)
            self._engine = None
            self._sessionmaker = None
            self._initialized = False
            logger.info("Postgres cache closed")

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        """Acquire and yield a database session for one cache operation."""
        if self._sessionmaker is None:
            raise RuntimeError("Postgres cache has not been initialized")
        session = self._sessionmaker()
        try:
            yield session
        except SQLAlchemyError:
            await session.rollback()
            raise
        finally:
            await session.aclose()

    async def get(self, key: str) -> Any | None:
        """Return the cached value for key, or None."""
        if not self._circuit_breaker.can_attempt() or self._sessionmaker is None:
            return None

        try:
            async with self._session() as session:
                result = await session.execute(
                    text(
                        "SELECT value FROM cache_entries "
                        "WHERE key = :key AND (expires_at IS NULL OR expires_at > now())"
                    ),
                    {"key": key},
                )
                row = result.one_or_none()
            self._circuit_breaker.record_success()
            if row is None:
                return None
            return json.loads(row[0])
        except Exception as exc:
            self._circuit_breaker.record_failure()
            logger.warning("Postgres cache get failed: %s", exc)
            return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Store value under key; return whether the write succeeded."""
        if not self._circuit_breaker.can_attempt() or self._sessionmaker is None:
            return False

        try:
            serialized = json.dumps(value, default=str)
            expires_clause = (
                "now() + :ttl_seconds * interval \\'1 second\\'"
                if ttl is not None
                else "NULL"
            )
            async with self._session() as session:
                await session.execute(
                    text(
                        "INSERT INTO cache_entries (key, value, ttl, expires_at) "
                        "VALUES (:key, :value, :ttl, " + expires_clause + ") "
                        "ON CONFLICT (key) DO UPDATE SET "
                        "value = EXCLUDED.value, "
                        "ttl = EXCLUDED.ttl, "
                        "expires_at = EXCLUDED.expires_at"
                    ),
                    {"key": key, "value": serialized, "ttl": ttl},
                )
                await session.commit()
            self._circuit_breaker.record_success()
            return True
        except Exception as exc:
            self._circuit_breaker.record_failure()
            logger.warning("Postgres cache set failed: %s", exc)
            return False

    async def delete(self, key: str) -> bool:
        """Remove key; return whether the delete succeeded."""
        if not self._circuit_breaker.can_attempt() or self._sessionmaker is None:
            return False

        try:
            async with self._session() as session:
                await session.execute(
                    text("DELETE FROM cache_entries WHERE key = :key"),
                    {"key": key},
                )
                await session.commit()
            self._circuit_breaker.record_success()
            return True
        except Exception as exc:
            self._circuit_breaker.record_failure()
            logger.warning("Postgres cache delete failed: %s", exc)
            return False

    async def clear_pattern(self, pattern: str) -> int:
        """Remove every key matching pattern; return the deletion count."""
        if not self._circuit_breaker.can_attempt() or self._sessionmaker is None:
            return 0

        try:
            async with self._session() as session:
                result = await session.execute(
                    text("DELETE FROM cache_entries WHERE key LIKE :pattern"),
                    {"pattern": pattern},
                )
                row_count = result.rowcount
                await session.commit()
            self._circuit_breaker.record_success()
            return row_count or 0
        except Exception as exc:
            self._circuit_breaker.record_failure()
            logger.warning("Postgres cache clear_pattern failed: %s", exc)
            return 0

    def get_generation(self, key: str) -> str | int | None:
        """Return the generation counter for a user (GenerationCacheClient interface)."""
        if not self._circuit_breaker.can_attempt() or self._sessionmaker is None:
            return None
        try:
            async def _get() -> str | int | None:
                async with self._session() as session:
                    result = await session.execute(
                        text("SELECT generation FROM cache_generations WHERE user_id = :uid"),
                        {"uid": key.split(chr(58))[-1]},
                    )
                    row = result.one_or_none()
                    return str(row[0]) if row is not None else None
            import asyncio
            return asyncio.get_event_loop().run_until_complete(_get())
        except Exception as exc:
            self._circuit_breaker.record_failure()
            logger.warning("Postgres cache get_generation failed: %s", exc)
            return None

    def incr_generation(self, key: str) -> int:
        """Atomically increment a user generation counter and return the new value."""
        if not self._circuit_breaker.can_attempt() or self._sessionmaker is None:
            raise RuntimeError("Postgres cache is unavailable for incr")
        try:
            async def _incr() -> int:
                user_id = key.split(chr(58))[-1]
                async with self._session() as session:
                    result = await session.execute(
                        text(
                            "INSERT INTO cache_generations (user_id, generation) "
                            "VALUES (:uid, 1) "
                            "ON CONFLICT (user_id) DO UPDATE SET "
                            "generation = cache_generations.generation + 1 "
                            "RETURNING generation"
                        ),
                        {"uid": user_id},
                    )
                    row = result.one_or_none()
                    await session.commit()
                    return int(row[0]) if row is not None else 1
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(_incr())
            self._circuit_breaker.record_success()
            return result
        except Exception as exc:
            self._circuit_breaker.record_failure()
            logger.warning("Postgres cache incr_generation failed: %s", exc)
            raise


# ---------------------------------------------------------------------------
# Postgres key/value helpers (callable from sync wrappers used by the
# async generation protocol via fallback context)
# ---------------------------------------------------------------------------

def _pg_get_generation(user_id_str: str) -> str | None:
    """Return the generation counter (sync wrapper, used by PostgresCache)."""
    cache_obj: PostgresCache = cast(PostgresCache, cache)

    async def _run() -> str | None:
        async with cache_obj._session() as session:
            result = await session.execute(
                text("SELECT generation FROM cache_generations WHERE user_id = :uid"),
                {"uid": user_id_str},
            )
            row = result.one_or_none()
            return str(row[0]) if row is not None else None

    import asyncio
    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return loop.run_in_executor(pool, lambda: asyncio.run(_run())).result()
    except RuntimeError:
        return asyncio.run(_run())


def _pg_incr_generation(user_id_str: str) -> int:
    """Atomically increment a Postgres generation counter (sync wrapper)."""
    cache_obj: PostgresCache = cast(PostgresCache, cache)

    async def _run() -> int:
        async with cache_obj._session() as session:
            result = await session.execute(
                text(
                    "INSERT INTO cache_generations (user_id, generation) "
                    "VALUES (:uid, 1) "
                    "ON CONFLICT (user_id) DO UPDATE SET "
                    "generation = cache_generations.generation + 1 "
                    "RETURNING generation"
                ),
                {"uid": user_id_str},
            )
            row = result.one_or_none()
            await session.commit()
            return int(row[0]) if row is not None else 1

    import asyncio
    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return loop.run_in_executor(pool, lambda: asyncio.run(_run())).result()
    except RuntimeError:
        return asyncio.run(_run())


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------

def _arg_to_cache_string(value: Any) -> str | None:
    """Convert an argument value to a stable cache key string."""
    if value is None:
        return "None"

    if isinstance(value, (str, int, float, bool)):
        return str(value)

    arg_type = value.__class__.__name__
    if arg_type in _SKIP_TYPES:
        return None

    if hasattr(value, "id") and not isinstance(value, type):
        return f"{arg_type}:{value.id}"

    return str(value)


def _generate_cache_key(
    func_name: str,
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> str:
    """Generate a cache key from function name and arguments."""
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


# ---------------------------------------------------------------------------
# @cached decorator
# ---------------------------------------------------------------------------

def cached(
    ttl: int | TTL = TTL.MEDIUM,
    *,
    falsy_ttl: int | None = None,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Decorator to cache async function results.

    User-scoped calls are routed through the bounded generation namespace so
    mutations can invalidate every cached view for one user with one generation
    bump. Calls without a resolvable user identity retain the legacy key behavior.
    """

    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        actual_ttl = _get_ttl_value(ttl) if isinstance(ttl, TTL) else ttl
        generation_wrapper: Callable[P, Awaitable[T]] | None = None

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            nonlocal generation_wrapper

            if _has_user_cache_scope(func, *args, **kwargs):
                if generation_wrapper is None:
                    from app.cache_generation import generation_cached

                    generation_wrapper = generation_cached(
                        ttl,
                        falsy_ttl=falsy_ttl,
                    )(func)
                return await generation_wrapper(*args, **kwargs)

            if not cache.is_initialized:
                return await func(*args, **kwargs)

            func_name = getattr(func, "__name__", func.__class__.__name__)
            cache_key = _generate_cache_key(func_name, func, args, kwargs)

            cached_value = await cache.get(cache_key)
            if cached_value is not None:
                logger.debug("Cache hit: %s", cache_key)
                return cast(T, cached_value)

            logger.debug("Cache miss: %s", cache_key)
            result = await func(*args, **kwargs)

            effective_ttl = falsy_ttl if falsy_ttl is not None and not result else actual_ttl
            if result or falsy_ttl is not None:
                await cache.set(cache_key, result, ttl=effective_ttl)

            return result

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Global cache singleton
# ---------------------------------------------------------------------------

cache: BaseCache = UpstashCache()


async def invalidate_cache(pattern: str) -> int:
    """Invalidate cache keys matching a pattern."""
    return await cache.clear_pattern(pattern)
