"""Retry utilities for database operations."""

import time
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.constants import DEADLOCK_INITIAL_DELAY, DEADLOCK_MAX_RETRIES


@contextmanager
def deadlock_retry(db: Session) -> Generator[None]:
    """Context manager that retries on deadlock with exponential backoff.

    Usage:
        with deadlock_retry(db):
            # database operations that might deadlock
            db.commit()
    """
    retries = 0
    while True:
        try:
            yield
            return  # Success, exit
        except OperationalError as e:
            if "deadlock" not in str(e).lower():
                raise
            db.rollback()
            retries += 1
            if retries >= DEADLOCK_MAX_RETRIES:
                raise RuntimeError(
                    f"Failed after {DEADLOCK_MAX_RETRIES} retries due to deadlock"
                ) from e
            delay = DEADLOCK_INITIAL_DELAY * (2 ** (retries - 1))
            time.sleep(delay)
