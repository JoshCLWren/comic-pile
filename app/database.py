"""Database connection and session management."""

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator
from enum import Enum

from fastapi import HTTPException, status
from sqlalchemy import event, exc as sqlalchemy_exc, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import QueuePool

from app.config import get_database_settings
from app.performance_diagnostics import record_database_query
from app.safe_logging import safe_connection_metadata, safe_exception_metadata

logger = logging.getLogger(__name__)

_db_settings = get_database_settings()

# Use test_database_url if in test environment, otherwise use database_url
if (
    os.getenv("ENVIRONMENT") == "test" or os.getenv("TEST_ENVIRONMENT") == "true"
) and _db_settings.test_database_url:
    DATABASE_URL = _db_settings.test_database_url
else:
    DATABASE_URL = _db_settings.database_url
ASYNC_DATABASE_URL = _db_settings.async_url

# Keep a missing or sleeping Neon endpoint from holding a serverless request open
# indefinitely. The dependency timeout covers the first pool acquisition, while
# asyncpg's connect and command timeouts bound lower-level network waits.
DATABASE_DEPENDENCY_TIMEOUT_SECONDS = 10.0
DATABASE_CONNECT_TIMEOUT_SECONDS = 10.0
DATABASE_COMMAND_TIMEOUT_SECONDS = 8.0

# Database retry configuration for Neon scale-to-zero wake-up resilience
# Bounded retry with exponential backoff for transient connection failures
DB_MAX_RETRY_ATTEMPTS = 3
DB_INITIAL_RETRY_DELAY_SECONDS = 0.5
DB_MAX_RETRY_DELAY_SECONDS = 2.0

# Pool configuration from environment (with optimized defaults for Vercel Fluid Compute)
# Recommended based on benchmarking: size=2, no overflow, no pre-ping
# See docs/pool_benchmark_results.md for rationale
POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "2"))
MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "0"))
POOL_PRE_PING = os.getenv("DB_POOL_PRE_PING", "false").lower() == "true"
POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "3600"))

# Database circuit breaker configuration
DB_CIRCUIT_FAILURE_THRESHOLD = 5
DB_CIRCUIT_RESET_TIMEOUT_SECONDS = 30


class CircuitState(Enum):
    """Circuit breaker states for database connections."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class DatabaseCircuitBreaker:
    """Circuit breaker for database connection resilience.

    Prevents retry storms during sustained database outages while allowing
    recovery when the database becomes available again.
    """

    def __init__(
        self,
        name: str = "database",
        failure_threshold: int = DB_CIRCUIT_FAILURE_THRESHOLD,
        reset_timeout_seconds: int = DB_CIRCUIT_RESET_TIMEOUT_SECONDS,
    ) -> None:
        """Initialize the database circuit breaker.

        Args:
            name: Name for logging/metrics.
            failure_threshold: Number of failures before opening circuit.
            reset_timeout_seconds: Seconds before attempting recovery.
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
        """Check if a connection attempt should be allowed."""
        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.OPEN and self._opened_at:
            if time.time() - self._opened_at >= self.reset_timeout_seconds:
                logger.info("Database circuit '%s': OPEN -> HALF_OPEN", self.name)
                self._state = CircuitState.HALF_OPEN
                return True
            return False

        # HALF_OPEN allows one attempt
        return True

    def reset(self) -> None:
        """Reset the circuit after a confirmed healthy connection."""
        if self._state != CircuitState.CLOSED:
            logger.info("Database circuit '%s': %s -> CLOSED", self.name, self._state.value)
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at = None

    def record_success(self) -> None:
        """Record successful connection."""
        if self._state == CircuitState.HALF_OPEN:
            logger.info("Database circuit '%s': HALF_OPEN -> CLOSED", self.name)
            self.reset()
        elif self._state == CircuitState.CLOSED:
            self._failure_count = 0

    def record_failure(self) -> None:
        """Record failed connection attempt."""
        self._failure_count += 1

        if self._state == CircuitState.HALF_OPEN:
            logger.warning("Database circuit '%s': HALF_OPEN -> OPEN", self.name)
            self._state = CircuitState.OPEN
            self._opened_at = time.time()
        elif self._state == CircuitState.CLOSED:
            if self._failure_count >= self.failure_threshold:
                logger.warning(
                    "Database circuit '%s': CLOSED -> OPEN (%d failures)",
                    self.name,
                    self._failure_count,
                )
                self._state = CircuitState.OPEN
                self._opened_at = time.time()


# Global database circuit breaker instance
_database_circuit_breaker = DatabaseCircuitBreaker()


def get_database_circuit_breaker() -> DatabaseCircuitBreaker:
    """Get the global database circuit breaker instance."""
    return _database_circuit_breaker


# Log only an allowlisted metadata projection. Rendering a URL, even with its
# password hidden, risks exposing usernames, query credentials, or encoded secrets.
logger.info(
    "Database configured",
    extra={
        "database": safe_connection_metadata(ASYNC_DATABASE_URL),
        "pool_size": POOL_SIZE,
        "max_overflow": MAX_OVERFLOW,
        "pool_pre_ping": POOL_PRE_PING,
        "pool_recycle": POOL_RECYCLE,
        "circuit_failure_threshold": DB_CIRCUIT_FAILURE_THRESHOLD,
        "circuit_reset_timeout_seconds": DB_CIRCUIT_RESET_TIMEOUT_SECONDS,
        "max_retry_attempts": DB_MAX_RETRY_ATTEMPTS,
    },
)

async_engine = create_async_engine(
    ASYNC_DATABASE_URL,
    pool_recycle=POOL_RECYCLE,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_timeout=DATABASE_CONNECT_TIMEOUT_SECONDS,
    pool_pre_ping=POOL_PRE_PING,
    connect_args={
        "timeout": DATABASE_CONNECT_TIMEOUT_SECONDS,
        "command_timeout": DATABASE_COMMAND_TIMEOUT_SECONDS,
    },
)


def _log_pool_state(pool: QueuePool, event_name: str) -> None:
    """Log current pool state for observability."""
    try:
        checked_out = pool.checkedout()
        checked_in = pool.checkedin()
        overflow = pool.overflow()
        logger.debug(
            "pool_state event=%s size=%d checked_out=%d checked_in=%d overflow=%d",
            event_name,
            pool.size(),
            checked_out,
            checked_in,
            overflow,
        )
    except Exception:
        # Never let observability break the application
        pass


@event.listens_for(async_engine.sync_engine.pool, "checkout")
def _on_checkout(dbapi_connection: object, connection_record: object, connection_proxy: object) -> None:
    """Record pool checkout state.

    The ``_comic_pile_last_query_started`` timestamp is stamped by
    ``_before_cursor_execute`` *after* the connection is handed out, so the
    elapsed value here represents idle-in-pool time since the last query
    started on this connection — not checkout latency.
    """
    del dbapi_connection, connection_proxy
    checkout_started = getattr(connection_record, "_comic_pile_last_query_started", None)
    if isinstance(checkout_started, float):
        elapsed_ms = (time.perf_counter() - checkout_started) * 1000
        logger.info("pool_checkout idle_since_last_query_ms=%.2f", elapsed_ms)
    _log_pool_state(async_engine.sync_engine.pool, "checkout")


@event.listens_for(async_engine.sync_engine.pool, "checkin")
def _on_checkin(dbapi_connection: object, connection_record: object) -> None:
    """Record pool checkin and state."""
    del dbapi_connection
    _log_pool_state(async_engine.sync_engine.pool, "checkin")


@event.listens_for(async_engine.sync_engine.pool, "connect")
def _on_connect(dbapi_connection: object, connection_record: object) -> None:
    """Record new physical connection creation."""
    del dbapi_connection, connection_record
    logger.info("pool_connect new_physical_connection_created=true")
    _log_pool_state(async_engine.sync_engine.pool, "connect")


@event.listens_for(async_engine.sync_engine.pool, "first_connect")
def _on_first_connect(dbapi_connection: object, connection_record: object) -> None:
    """Record first connection creation."""
    del dbapi_connection, connection_record
    logger.info("pool_first_connect")


@event.listens_for(async_engine.sync_engine.pool, "invalidate")
def _on_invalidate(dbapi_connection: object, connection_record: object, exception: object) -> None:
    """Record connection invalidation."""
    del dbapi_connection, connection_record
    logger.warning("pool_invalidate exception=%s", type(exception).__name__ if exception else "none")


@event.listens_for(async_engine.sync_engine, "before_cursor_execute")
def _before_cursor_execute(
    connection: object,
    cursor: object,
    statement: str,
    parameters: object,
    context: object,
    executemany: bool,
) -> None:
    """Start timing a SQL statement after a connection has been acquired."""
    # Mark checkout start time on the connection record if available
    try:
        conn_record = getattr(connection, "_connection_record", None)
        if conn_record is not None:
            conn_record._comic_pile_last_query_started = time.perf_counter()
    except Exception:
        pass
    del cursor, statement, parameters, executemany
    vars(context)["_comic_pile_query_started_at"] = time.perf_counter()


@event.listens_for(async_engine.sync_engine, "after_cursor_execute")
def _after_cursor_execute(
    connection: object,
    cursor: object,
    statement: str,
    parameters: object,
    context: object,
    executemany: bool,
) -> None:
    """Record SQL execution time in the active request diagnostics context."""
    del connection, cursor, statement, parameters, executemany
    started_at = vars(context).get("_comic_pile_query_started_at")
    if isinstance(started_at, float):
        record_database_query((time.perf_counter() - started_at) * 1000)


AsyncSessionLocal = async_sessionmaker(
    async_engine,
    autocommit=False,
    autoflush=True,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


def _is_transient_connection_error(error: BaseException) -> bool:
    """Check if an error is a transient connection failure that warrants retry.

    Args:
        error: The exception to check.

    Returns:
        True if the error is a transient connection failure (stale pooled connection,
        timeout, etc.), False otherwise.
    """
    # asyncio timeout
    if isinstance(error, TimeoutError):
        return True

    # SQLAlchemy timeout and DBAPI errors
    if isinstance(error, (sqlalchemy_exc.TimeoutError, sqlalchemy_exc.DBAPIError)):
        # Check for InterfaceError (stale/closed pooled connection)
        # and other transient connection errors
        orig = getattr(error, "orig", None)
        if orig is not None:
            # asyncpg exceptions
            error_type_name = type(orig).__name__
            # InterfaceError: stale pooled connection, connection closed unexpectedly
            # ConnectionDoesNotExistError: connection was closed
            # CannotConnectNowError: server not ready (waking up)
            transient_errors = {
                "InterfaceError",
                "ConnectionDoesNotExistError",
                "CannotConnectNowError",
                "PostgresConnectionError",
            }
            if error_type_name in transient_errors:
                return True

        # Also check the error message for common transient patterns
        error_msg = str(error).lower()
        transient_patterns = [
            "connection",
            "timeout",
            "closed",
            "invalidated",
            "pool",
        ]
        if any(pattern in error_msg for pattern in transient_patterns):
            return True

    return False


async def _attempt_connection_with_retry(
    session: AsyncSession, started_at: float
) -> bool:
    """Attempt to establish a database connection with bounded retry logic.

    Args:
        session: The SQLAlchemy async session.
        started_at: The timestamp when the overall attempt started.

    Returns:
        True if connection succeeded, False if all retries exhausted.

    Raises:
        HTTPException: If the circuit breaker is open or non-transient error occurs.
    """
    circuit_breaker = get_database_circuit_breaker()

    for attempt in range(DB_MAX_RETRY_ATTEMPTS):
        # Check circuit breaker before each attempt
        if not circuit_breaker.can_attempt():
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            logger.warning(
                "database_circuit_open duration_ms=%.2f circuit_state=%s",
                elapsed_ms,
                circuit_breaker.state.value,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database temporarily unavailable (circuit open)",
            )

        try:
            # Calculate remaining time budget
            elapsed = time.perf_counter() - started_at
            remaining_budget = DATABASE_DEPENDENCY_TIMEOUT_SECONDS - elapsed
            if remaining_budget <= 0:
                logger.warning(
                    "database_retry_budget_exhausted attempt=%d elapsed_ms=%.2f",
                    attempt + 1,
                    elapsed * 1000,
                )
                return False

            # Use the remaining budget for this connection attempt
            timeout = min(remaining_budget, DATABASE_CONNECT_TIMEOUT_SECONDS)
            async with asyncio.timeout(timeout):
                await session.connection()

            # Success - record and return
            circuit_breaker.record_success()
            logger.info(
                "database_connection_established attempt=%d duration_ms=%.2f",
                attempt + 1,
                (time.perf_counter() - started_at) * 1000,
            )
            return True

        except Exception as error:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            is_transient = _is_transient_connection_error(error)

            if is_transient:
                logger.warning(
                    "database_transient_connection_failure attempt=%d/%d elapsed_ms=%.2f error=%s",
                    attempt + 1,
                    DB_MAX_RETRY_ATTEMPTS,
                    elapsed_ms,
                    type(error).__name__,
                )
                circuit_breaker.record_failure()

                # If this was the last attempt, don't wait
                if attempt == DB_MAX_RETRY_ATTEMPTS - 1:
                    break

                # Bounded exponential backoff
                delay = min(
                    DB_INITIAL_RETRY_DELAY_SECONDS * (2**attempt),
                    DB_MAX_RETRY_DELAY_SECONDS,
                )
                logger.debug("database_retry_backoff delay_seconds=%.2f", delay)
                await asyncio.sleep(delay)
                continue
            else:
                # Non-transient error - fail immediately
                logger.error(
                    "database_non_transient_error attempt=%d elapsed_ms=%.2f error=%s",
                    attempt + 1,
                    elapsed_ms,
                    type(error).__name__,
                )
                circuit_breaker.record_failure()
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Database temporarily unavailable",
                ) from error

    # All retries exhausted
    circuit_breaker.record_failure()
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    logger.error(
        "database_connection_failed_all_retries attempts=%d duration_ms=%.2f",
        DB_MAX_RETRY_ATTEMPTS,
        elapsed_ms,
    )
    return False


async def get_db() -> AsyncIterator[AsyncSession]:
    """Get an async database session with bounded first connection acquisition and retry.

    Implements retry logic for transient connection failures (e.g., Neon scale-to-zero
    wake-up, stale pooled connections) with bounded backoff and circuit breaker.

    Yields:
        AsyncSession: Database session for use in dependency injection.

    Raises:
        HTTPException: If connection cannot be established within the configured
            dependency timeout after retries, or if circuit breaker is open.
    """
    started_at = time.perf_counter()
    try:
        async with AsyncSessionLocal() as session:
            connected = await _attempt_connection_with_retry(session, started_at)
            if not connected:
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                logger.warning(
                    "database_dependency_unavailable duration_ms=%.2f limit_seconds=%.1f",
                    elapsed_ms,
                    DATABASE_DEPENDENCY_TIMEOUT_SECONDS,
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Database temporarily unavailable",
                )

            logger.info(
                "database_dependency_opened duration_ms=%.2f",
                (time.perf_counter() - started_at) * 1000,
            )
            try:
                yield session
            finally:
                await session.close()
    except HTTPException:
        # Re-raise HTTP exceptions (including 503 from circuit breaker)
        raise
    except (TimeoutError, sqlalchemy_exc.TimeoutError, sqlalchemy_exc.DBAPIError) as error:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.warning(
            "database_dependency_unavailable duration_ms=%.2f limit_seconds=%.1f error=%s",
            elapsed_ms,
            DATABASE_DEPENDENCY_TIMEOUT_SECONDS,
            type(error).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database temporarily unavailable",
        ) from error


async def test_database_connection() -> bool:
    """Test database connection.

    Returns:
        True if connection successful, False otherwise.
    """
    try:
        async with asyncio.timeout(DATABASE_DEPENDENCY_TIMEOUT_SECONDS):
            async with AsyncSessionLocal() as session:
                await session.execute(text("SELECT 1"))
                return True
    except Exception as error:
        logger.error(
            "Database connection test failed",
            extra={"database_error": safe_exception_metadata(error)},
        )
        return False
