"""Retry utilities for database operations."""

import time
from collections.abc import Callable
from typing import TypeVar

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import DEADLOCK_INITIAL_DELAY, DEADLOCK_MAX_RETRIES

T = TypeVar("T")


async def with_deadlock_retry[T](db: AsyncSession, operation: Callable[[], T]) -> T:
    """Execute a database operation with retry on deadlock.

    Args:
        db: Database session
        operation: Callable that performs the database operation

    Returns:
        The result of the operation

    Raises:
        RuntimeError: If max retries exceeded
        OperationalError: If error is not a deadlock

    Usage:
        def do_db_work():
            # database operations
            db.commit()
            return some_value

        result = await with_deadlock_retry(db, do_db_work)
    """
    retries = 0
    while True:
        try:
            return operation()
        except OperationalError as e:
            if "deadlock" not in str(e).lower():
                raise
            await db.rollback()
            retries += 1
            if retries >= DEADLOCK_MAX_RETRIES:
                raise RuntimeError(
                    f"Failed after {DEADLOCK_MAX_RETRIES} retries due to deadlock"
                ) from e
            delay = DEADLOCK_INITIAL_DELAY * (2 ** (retries - 1))
            time.sleep(delay)
