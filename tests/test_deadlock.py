"""Tests for deadlock handling in concurrent operations."""

import os
import threading
from datetime import UTC, datetime

import pytest

from app.database import SessionLocal
from app.models import Session as SessionModel
from comic_pile.session import get_or_create
from sqlalchemy import delete


def test_get_or_create_concurrent_no_deadlock(db, sample_data):
    """Test that concurrent get_or_create calls don't deadlock.

    Regression test for BUG-158: DeadlockDetected error during concurrent operations.
    Multiple threads calling get_or_create simultaneously should not deadlock.
    """
    if "sqlite" in os.getenv("TEST_DATABASE_URL", os.getenv("DATABASE_URL", "")):
        pytest.skip("Concurrent session creation test requires PostgreSQL advisory locks")

    for session in sample_data["sessions"]:
        session.ended_at = datetime.now(UTC)
    db.commit()

    results = []
    exceptions = []

    def worker():
        inner_db = SessionLocal()
        try:
            session = get_or_create(inner_db, user_id=1)
            results.append(session.id)
        except Exception as e:
            exceptions.append(e)
        finally:
            inner_db.close()

    threads = [threading.Thread(target=worker) for _ in range(5)]

    for t in threads:
        t.start()

    for t in threads:
        t.join(timeout=10)

    assert len(exceptions) == 0, f"Concurrent operations raised exceptions: {exceptions}"
    assert len(results) == 5, "All threads should complete"
    assert len(set(results)) == 1, "All threads should return the same session ID"


def test_get_or_create_concurrent_no_duplicates(db):
    """Test that concurrent session creation doesn't create duplicate sessions."""
    if "sqlite" in os.getenv("TEST_DATABASE_URL", os.getenv("DATABASE_URL", "")):
        pytest.skip("Concurrent session creation test requires PostgreSQL advisory locks")

    db.execute(delete(SessionModel))
    db.commit()

    results = []
    exceptions = []

    def worker():
        inner_db = SessionLocal()
        try:
            session = get_or_create(inner_db, user_id=1)
            results.append((session.id, session.started_at))
        except Exception as e:
            exceptions.append(e)
        finally:
            inner_db.close()

    threads = [threading.Thread(target=worker) for _ in range(10)]

    for t in threads:
        t.start()

    for t in threads:
        t.join(timeout=10)

    assert len(exceptions) == 0, f"Concurrent operations raised exceptions: {exceptions}"
    assert len(results) == 10, "All threads should complete"

    session_ids = [r[0] for r in results]
    assert len(set(session_ids)) == 1, "All threads should return the same session ID"
