"""Application cache provider: one small interface over Redis transports.

Callers depend only on this interface:

- TTL: SHORT/MEDIUM/LONG tiers whose values resolve from settings at call time
- cached: decorator that caches async function results
- invalidate_cache: delete keys matching a pattern
- cache: process-wide provider instance (get/set/delete/clear_pattern/ping)
- ttl_seconds / generate_cache_key: tier and logical-key helpers shared with
  the user-scoped namespace in :mod:`app.cache_generation`
- CacheClient: structural type describing the caller-facing operations

Transport specifics live below the interface and are implementation details:
Upstash REST and local redis-py clients, lazy connection lifecycle, the
circuit breaker, and JSON value codecs.

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
from typing import Any, ParamSpec, Protocol, TypeVar, cast

import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from upstash_redis.asyncio import Redis as UpstashRedis

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")

__all__ = [
    "CacheClient",
    "PostgresCache",
    "TTL",
    "UpstashCache",
    "cache",
    "cached",
    "generate_cache_key",
    "invalidate_cache",
    "ttl_seconds",
]

# --- Public provider interface ------------------------------------------------


class TTL(enum.Enum):
    """Cache TTL tiers - values are resolved from RedisSettings at runtime."""

    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


def ttl_seconds(tier: TTL) -> int:
    """Resolve one TTL tier to its configured duration in seconds.

    Args:
        tier: Named TTL tier.

    Returns:
        TTL value in seconds from RedisSettings.
    """
    # Import here to avoid circular imports
    from app.config import get_redis_settings

    settings = get_redis_settings()
    tier_map = {
        TTL.SHORT: settings.cache_ttl_short,
        TTL.MEDIUM: settings.cache_ttl_medium,
        TTL.LONG: settings.cache_ttl_long,
    }
    return tier_map[tier]


class CacheClient(Protocol):
    """Small provider interface that application callers may depend on."""

    @property
    def is_initialized(self) -> bool:
        """Return whether a cache transport is configured and ready."""
        ...

    async def ping(self) -> None:
        """Verify transport connectivity; raise when unavailable."""
        ...

    async def get(self, key: str) -> Any | None:
        """Return the cached value for a key, or None on a miss."""
        ...

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Store a value under a key with an optional TTL in seconds."""
        ...

    async def delete(self, key: str) -> bool:
        """Delete one key."""
        ...

    async def clear_pattern(self, pattern: str) -> int:
        """Delete every key matching a glob pattern; return the count."""
        ...

    def record_failure(self) -> None:
        """Record one externally observed cache failure."""
        ...


def generate_cache_key(
    func_name: str,
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> str:
    """Generate a stable logical cache key from function name and arguments.

    Uses inspect.signature to bind arguments in declaration order,
    producing stable keys regardless of whether callers use positional
    or keyword arguments.

    Args:
        func_name: Name of the cached function.
        func: The cached function whose signature binds the arguments.
        args: Positional arguments from the call site.
        kwargs: Keyword arguments from the call site.

    Returns:
        Logical cache key shared by the legacy and generation namespaces.
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
        actual_ttl = ttl_seconds(ttl) if isinstance(ttl, TTL) else ttl
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
            cache_key = generate_cache_key(func_name, func, args, kwargs)

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


# --- Transport internals ------------------------------------------------------
#
# Everything below is an implementation detail of this module. Application
# callers must interact with caching only through the interface above.


_SKIP_TYPES = frozenset({"AsyncSession", "Session", "Engine", "Request"})
_CONNECT_TIMEOUT_SECONDS = 5.0


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


def _reconstruct_value(value: Any) -> Any:
    """Reconstruct a value from deserialized JSON, restoring tagged types."""
    if isinstance(value, dict) and "__type__" in value:
        type_tag = value["__type__"]
        if type_tag == "set":
            return {_reconstruct_value(v) for v in value["values"]}
    if isinstance(value, dict):
        return {k: _reconstruct_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_reconstruct_value(v) for v in value]
    return value


def _prepare_value(value: Any) -> Any:
    """Prepare a value for JSON serialization.

    Handles Pydantic models, SQLAlchemy models, sets, and other types.
    """
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, set):
        return {"__type__": "set", "values": [_prepare_value(v) for v in value]}

    if isinstance(value, dict):
        return {k: _prepare_value(v) for k, v in value.items()}

    if isinstance(value, list):
        return [_prepare_value(v) for v in value]

    if isinstance(value, tuple):
        return [_prepare_value(v) for v in value]

    # Pydantic v2 models
    if hasattr(value, "model_dump"):
        return _prepare_value(value.model_dump())

    # Pydantic v1 models / attrs
    if hasattr(value, "dict"):
        return _prepare_value(value.dict())

    # SQLAlchemy models: convert to dict via __dict__ but skip internal attrs
    if hasattr(value, "_sa_instance_state"):
        state = {c.key: getattr(value, c.key) for c in value.__table__.columns}
        return _prepare_value(state)

    # Datetime objects
    if hasattr(value, "isoformat"):
        return value.isoformat()

    return str(value)


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


class UpstashCache:
    """Internal transport implementing CacheClient over Upstash REST or local Redis.

    Adds lazy connection lifecycle, a circuit breaker, and JSON value codecs on
    top of the provider operations. Application code must use the module-level
    ``cache`` instance instead of constructing this class directly.
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
        """Close the Redis connection and reset singleton state.

        Always clears the initialized flag even when no client is present, so a
        previously-initialized singleton can always be reconfigured from scratch.
        """
        client = self._client
        self._client = None
        self._initialized = False
        if client is not None:
            if not self._is_upstash:
                await client.aclose()
            logger.info("Redis cache closed")

    async def ping(self) -> None:
        """Ping the active transport to verify connectivity.

        Raises:
            RuntimeError: If the cache has not been initialized.
        """
        client = self._client
        if not self.is_initialized or client is None:
            raise RuntimeError("Cache is not initialized")
        await client.ping()

    def record_failure(self) -> None:
        """Record one externally observed failure, such as a wrapper timeout."""
        self._circuit_breaker.record_failure()

    async def incr(self, key: str) -> int:
        """Increment one integer counter key.

        Deliberately bypasses the circuit breaker so user-cache invalidation
        keeps its existing fail-open semantics.

        Args:
            key: Counter key.

        Returns:
            Newly incremented counter value.
        """
        client = self._client
        if client is None:
            raise RuntimeError("Cache client is unavailable")
        return await client.incr(key)

    async def get_generation(self, key: str) -> int:
        """Read a generation/integer counter value, defaulting to zero."""
        client = self._client
        if not self.is_initialized or client is None:
            return 0
        try:
            raw = await client.get(key)
        except Exception:
            return 0
        if raw is None:
            return 0
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    async def eval_script(self, script: str, keys: list[str], args: list[str]) -> Any:
        """Run one Lua script atomically using each transport's convention.

        Args:
            script: Lua script source.
            keys: Script keys.
            args: Script arguments.

        Returns:
            Raw transport response.
        """
        client = self._client
        if client is None:
            raise RuntimeError("Cache client is unavailable")
        if self._is_upstash:
            return await client.eval(script, keys=keys, args=args)
        return await client.eval(script, len(keys), *keys, *args)

    def decode_value(self, raw: object) -> Any:
        """Decode a stored cache payload back into Python objects.

        Args:
            raw: Stored payload as text or bytes.

        Returns:
            Reconstructed value with tagged containers restored.

        Raises:
            ValueError: If the payload is not JSON text.
        """
        if isinstance(raw, bytes):
            raw = raw.decode()
        elif not isinstance(raw, str):
            raise ValueError("Cached value must be JSON text")
        return _reconstruct_value(json.loads(raw))

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
            return _reconstruct_value(json.loads(result))
        except Exception as e:
            self._circuit_breaker.record_failure()
            logger.warning("Cache get failed: %s", e)
            return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Set a value in cache."""
        if not self.is_initialized or not self._circuit_breaker.can_attempt():
            return False

        if self._client is None:
            return False

        try:
            prepared = _prepare_value(value)
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


# --- Postgres provider -------------------------------------------------------
#
# A provider backed by the application's primary Postgres database. It implements
# the same :class:`CacheClient` contract as the Redis transport so callers and the
# generation namespace are backend-agnostic. Values are JSON-serialized and stored
# in ``cache_entries`` (namespace, cache_key, JSONB value); per-user generation
# counters live in ``cache_generations``. The schema ships with migration
# c85500000001 and is verified by tests/test_cache_schema.py.

_CACHE_NAMESPACE = "app"
# cache_entries.expires_at is NOT NULL, so TTL-less entries receive this sentinel
# window instead of modeling a nullable expiry in SQL.
_NO_TTL_SECONDS = 60 * 60 * 24 * 30


class PostgresCache:
    """CacheClient implementation backed by Postgres (RESP-free, Valkey-ready).

    This provider keeps the Redis-protocol client generic by not depending on any
    RESP/Upstash specifics; it speaks SQL only. After repeated failures it demotes
    to fail-open for the process lifetime so a sick database never turns optional
    caching into a request dependency (no per-request ping-pong).
    """

    _instance: PostgresCache | None = None

    def __new__(cls) -> PostgresCache:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._engine: AsyncEngine | None = None
        self._circuit_breaker = CircuitBreaker(name="postgres-cache")
        self._initialized = False
        self._demoted = False

    @property
    def is_initialized(self) -> bool:
        return self._initialized and not self._demoted and self._engine is not None

    def _maybe_demote(self) -> None:
        """Permanently fail-open for the process lifetime after repeated failures."""
        if self._circuit_breaker.state == CircuitState.OPEN:
            self._demoted = True

    async def initialize(self, database_url: str) -> None:
        """Create an async engine and verify connectivity.

        Args:
            database_url: ``postgresql+asyncpg://`` connection string.

        Raises:
            Exception: If the engine cannot be created or Postgres is unreachable.
        """
        if self._initialized:
            logger.warning("Postgres cache already initialized")
            return
        # Reuse a small dedicated pool; the cache is best-effort, not a primary path.
        self._engine = create_async_engine(
            database_url,
            pool_size=2,
            max_overflow=0,
            pool_pre_ping=True,
            connect_args={"timeout": _CONNECT_TIMEOUT_SECONDS},
        )
        await self.ping()
        self._circuit_breaker.reset()
        self._initialized = True
        self._demoted = False
        logger.info("Postgres cache configured")

    async def close(self) -> None:
        """Close the engine and reset singleton state.

        Always clears the initialized flag even when no engine is present, so a
        previously-initialized singleton can always be reconfigured from scratch.
        """
        engine = self._engine
        self._engine = None
        self._initialized = False
        if engine is not None:
            await engine.dispose()
            logger.info("Postgres cache closed")

    async def ping(self) -> None:
        """Verify database connectivity; raise when unavailable.

        Raises:
            RuntimeError: If the cache has not been initialized.
        """
        engine = self._engine
        if engine is None:
            raise RuntimeError("Cache is not initialized")
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    def record_failure(self) -> None:
        """Record one externally observed failure and apply the demotion policy."""
        self._circuit_breaker.record_failure()
        self._maybe_demote()

    async def get(self, key: str) -> Any | None:
        engine = self._engine
        if (
            engine is None
            or not self.is_initialized
            or not self._circuit_breaker.can_attempt()
        ):
            return None
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text(
                        "SELECT value FROM cache_entries "
                        "WHERE namespace = :ns AND cache_key = :k AND expires_at > now()"
                    ),
                    {"ns": _CACHE_NAMESPACE, "k": key},
                )
                row = result.scalar_one_or_none()
            self._circuit_breaker.record_success()
            if row is None:
                return None
            if isinstance(row, str):
                return _reconstruct_value(json.loads(row))
            # SQLAlchemy+asyncpg may return already-decoded JSONB (dict/list)
            return _reconstruct_value(row)
        except Exception as e:
            self._circuit_breaker.record_failure()
            self._maybe_demote()
            logger.warning("Postgres cache get failed: %s", e)
            return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        engine = self._engine
        if (
            engine is None
            or not self.is_initialized
            or not self._circuit_breaker.can_attempt()
        ):
            return False
        if ttl is not None and ttl <= 0:
            return await self.delete(key)
        effective_ttl = ttl if ttl is not None else _NO_TTL_SECONDS
        try:
            prepared = _prepare_value(value)
            data = json.dumps(prepared, default=str)
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO cache_entries (namespace, cache_key, value, "
                        "expires_at, created_at) "
                        "VALUES (:ns, :k, CAST(:v AS JSONB), "
                        "now() + make_interval(secs => :t), now()) "
                        "ON CONFLICT (namespace, cache_key) DO UPDATE "
                        "SET value = EXCLUDED.value, expires_at = EXCLUDED.expires_at"
                    ),
                    {"ns": _CACHE_NAMESPACE, "k": key, "v": data, "t": effective_ttl},
                )
            self._circuit_breaker.record_success()
            return True
        except Exception as e:
            self._circuit_breaker.record_failure()
            self._maybe_demote()
            logger.warning("Postgres cache set failed: %s", e)
            return False

    async def delete(self, key: str) -> bool:
        engine = self._engine
        if (
            engine is None
            or not self.is_initialized
            or not self._circuit_breaker.can_attempt()
        ):
            return False
        try:
            async with engine.begin() as conn:
                result = await conn.execute(
                    text(
                        "DELETE FROM cache_entries "
                        "WHERE namespace = :ns AND cache_key = :k RETURNING cache_key"
                    ),
                    {"ns": _CACHE_NAMESPACE, "k": key},
                )
                deleted = len(result.fetchall())
            self._circuit_breaker.record_success()
            return deleted > 0
        except Exception as e:
            self._circuit_breaker.record_failure()
            self._maybe_demote()
            logger.warning("Postgres cache delete failed: %s", e)
            return False

    async def clear_pattern(self, pattern: str) -> int:
        engine = self._engine
        if (
            engine is None
            or not self.is_initialized
            or not self._circuit_breaker.can_attempt()
        ):
            return 0
        like = pattern.replace("*", "%").replace("?", "_")
        try:
            async with engine.begin() as conn:
                result = await conn.execute(
                    text(
                        "DELETE FROM cache_entries "
                        "WHERE namespace = :ns AND cache_key LIKE :pat RETURNING cache_key"
                    ),
                    {"ns": _CACHE_NAMESPACE, "pat": like},
                )
                deleted = len(result.fetchall())
            self._circuit_breaker.record_success()
            return deleted
        except Exception as e:
            self._circuit_breaker.record_failure()
            self._maybe_demote()
            logger.warning("Postgres cache clear_pattern failed: %s", e)
            return 0

    async def incr(self, key: str) -> int:
        """Increment one generation counter row.

        Deliberately bypasses the circuit breaker so user-cache invalidation
        keeps its existing fail-open semantics.

        Args:
            key: Generation-counter scope key.

        Returns:
            Newly incremented counter value.

        Raises:
            RuntimeError: If the cache has not been initialized.
        """
        engine = self._engine
        if engine is None or not self.is_initialized:
            raise RuntimeError("Cache is not initialized")
        try:
            async with engine.begin() as conn:
                result = await conn.execute(
                    text(
                        "INSERT INTO cache_generations (scope, generation) VALUES (:s, 1) "
                        "ON CONFLICT (scope) DO UPDATE "
                        "SET generation = cache_generations.generation + 1 "
                        "RETURNING generation"
                    ),
                    {"s": key},
                )
                value = result.scalar_one()
            self._circuit_breaker.record_success()
            return int(value)
        except Exception as e:
            self._circuit_breaker.record_failure()
            self._maybe_demote()
            logger.warning("Postgres cache incr failed: %s", e)
            raise

    async def get_generation(self, key: str) -> int:
        """Read a generation/integer counter value, defaulting to zero."""
        engine = self._engine
        if engine is None or not self.is_initialized:
            return 0
        try:
            async with engine.connect() as conn:
                row = await conn.execute(
                    text("SELECT generation FROM cache_generations WHERE scope = :s"),
                    {"s": key},
                )
                value = row.scalar_one_or_none()
            self._circuit_breaker.record_success()
            return int(value) if value is not None else 0
        except Exception as e:
            self._circuit_breaker.record_failure()
            self._maybe_demote()
            logger.warning("Postgres cache get_generation failed: %s", e)
            return 0

    async def atomic_generation_read(
        self, generation_key: str, value_prefix: str, normalized: str
    ) -> list[Any]:
        """Read the active generation and matching value atomically (Postgres).

        Mirrors the Redis Lua path: returns ``[generation, raw_value]`` where
        ``raw_value`` is the stored JSON payload (or ``None`` on a miss).
        The payload may be returned as decoded JSONB (dict/list) or as text,
        depending on the asyncpg/SQLAlchemy decoding.
        """
        engine = self._engine
        if engine is None or not self.is_initialized:
            return [0, None]
        try:
            async with engine.begin() as conn:
                gen_row = await conn.execute(
                    text("SELECT generation FROM cache_generations WHERE scope = :s"),
                    {"s": generation_key},
                )
                gen = gen_row.scalar_one_or_none()
                generation = int(gen) if gen is not None else 0
                value_key = f"{value_prefix}{generation}:{normalized}"
                val_row = await conn.execute(
                    text(
                        "SELECT value FROM cache_entries "
                        "WHERE namespace = :ns AND cache_key = :k AND expires_at > now()"
                    ),
                    {"ns": _CACHE_NAMESPACE, "k": value_key},
                )
                raw = val_row.scalar_one_or_none()
                # Normalize JSONB payload to text for the shared decode path:
                # Postgres may return already-decoded dict/list; callers expect
                # a JSON text string akin to the Redis transport.
                if isinstance(raw, (dict, list)):
                    raw = json.dumps(raw)
                elif isinstance(raw, bytes):
                    raw = raw.decode()
            self._circuit_breaker.record_success()
            return [generation, raw]
        except Exception as e:
            self._circuit_breaker.record_failure()
            self._maybe_demote()
            logger.warning("Postgres generation read failed: %s", e)
            return [0, None]

    def decode_value(self, raw: object) -> Any:
        """Decode a stored cache payload back into Python objects.

        Args:
            raw: Stored payload as text, bytes, or already-decoded JSONB.

        Returns:
            Reconstructed value with tagged containers restored.

        Raises:
            ValueError: If the payload is not JSON text or a decoded JSON value.
        """
        if isinstance(raw, (dict, list)):
            return _reconstruct_value(raw)
        if isinstance(raw, bytes):
            raw = raw.decode()
        elif not isinstance(raw, str):
            raise ValueError("Cached value must be JSON text")
        return _reconstruct_value(json.loads(raw))


# --- Provider router ---------------------------------------------------------
#
# ``cache`` is a single stable process-wide instance. Startup selects the backend
# (Postgres or Redis) once; callers and :mod:`app.cache_generation` always bind to
# this same object, so swapping the backend never strands a previously imported
# reference the way reassigning the module global would.


class CacheRouter:
    """Routes caller-facing cache operations to the configured backend."""

    def __init__(self) -> None:
        self._backend: Any = None
        self._provider_kind = "off"
        self._demoted = False
        # Kept for backward-compatible test teardown that pokes these attributes.
        self._client: Any = None
        self._initialized = False

    # -- configuration --------------------------------------------------------

    async def _build_backend(self, provider: str, **kwargs: Any) -> Any:
        if provider == "postgres":
            backend = PostgresCache()
            # Singletons may carry state from a previous configuration; force a
            # deterministic rebuild so configure() always yields a fresh backend.
            await backend.close()
            await backend.initialize(database_url=kwargs["database_url"])
            return backend
        if provider == "redis":
            backend = UpstashCache()
            await backend.close()
            await backend.initialize(
                url=kwargs.get("url"),
                token=kwargs.get("token"),
                local_url=kwargs.get("local_url"),
            )
            return backend
        raise ValueError(f"Unknown cache provider: {provider}")

    async def configure(self, provider: str, **kwargs: Any) -> None:
        """Select and initialize the configured backend provider.

        Raises:
            Exception: When the chosen backend fails to initialize; callers
                should catch this and invoke :meth:`demote`.
        """
        backend = await self._build_backend(provider, **kwargs)
        self._backend = backend
        self._provider_kind = provider
        self._demoted = False
        self._client = getattr(backend, "_client", None)
        self._initialized = True

    async def initialize(
        self,
        url: str | None = None,
        token: str | None = None,
        local_url: str | None = None,
    ) -> None:
        """Backward-compatible redis initialization used by tests/fixtures."""
        await self.configure(
            "redis", url=url, token=token, local_url=local_url
        )

    async def demote(self) -> None:
        """Permanently fail-open for the process lifetime."""
        self._demoted = True
        self._provider_kind = "off"
        self._initialized = False
        self._client = None
        backend = self._backend
        self._backend = None
        if backend is not None:
            try:
                await backend.close()
            except Exception as exc:  # pragma: no cover - best effort teardown
                logger.warning("Cache backend teardown failed: %s", exc)

    async def close(self) -> None:
        backend = self._backend
        self._backend = None
        self._client = None
        self._initialized = False
        self._provider_kind = "off"
        self._demoted = False
        if backend is not None:
            await backend.close()

    # -- introspection --------------------------------------------------------

    @property
    def is_initialized(self) -> bool:
        return (
            self._backend is not None
            and self._backend.is_initialized
            and not self._demoted
        )

    @property
    def provider_kind(self) -> str:
        return self._provider_kind

    # -- delegated operations -------------------------------------------------

    async def ping(self) -> None:
        if self._backend is None or self._demoted:
            raise RuntimeError("Cache is not initialized")
        await self._backend.ping()

    def record_failure(self) -> None:
        if self._backend is not None:
            self._backend.record_failure()

    async def get(self, key: str) -> Any | None:
        if self._backend is None or self._demoted:
            return None
        return await self._backend.get(key)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        if self._backend is None or self._demoted:
            return False
        return await self._backend.set(key, value, ttl=ttl)

    async def delete(self, key: str) -> bool:
        if self._backend is None or self._demoted:
            return False
        return await self._backend.delete(key)

    async def clear_pattern(self, pattern: str) -> int:
        if self._backend is None or self._demoted:
            return 0
        return await self._backend.clear_pattern(pattern)

    async def incr(self, key: str) -> int:
        if self._backend is None or self._demoted:
            raise RuntimeError("Cache is not initialized")
        return await self._backend.incr(key)

    async def get_generation(self, key: str) -> int:
        if self._backend is None or self._demoted:
            return 0
        return await self._backend.get_generation(key)

    async def eval_script(self, script: str, keys: list[str], args: list[str]) -> Any:
        if self._backend is None or self._demoted:
            raise RuntimeError("Cache is not initialized")
        return await self._backend.eval_script(script, keys=keys, args=args)

    async def atomic_generation_read(
        self, generation_key: str, value_prefix: str, normalized: str
    ) -> list[Any]:
        if self._backend is None or self._demoted:
            return [0, None]
        return await self._backend.atomic_generation_read(
            generation_key, value_prefix, normalized
        )

    def decode_value(self, raw: object) -> Any:
        if self._backend is None:
            raise RuntimeError("Cache is not initialized")
        return self._backend.decode_value(raw)


# Process-wide provider instance. Callers depend only on this object; the active
# backend (Postgres or Redis) is chosen once at startup via ``cache.configure``.
cache = CacheRouter()
