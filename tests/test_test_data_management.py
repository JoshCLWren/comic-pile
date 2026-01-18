"""Test data management tests."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import Event, Session as SessionModel, Thread, User


def test_seed_data_marks_as_test(db):
    """Test that seeded data is marked as test data."""
    user = db.execute(select(User).where(User.id == 1)).scalar_one_or_none()
    if user is None:
        user = User(id=1, username="test_user")
        db.add(user)
        db.commit()
        db.refresh(user)

    thread = Thread(
        title="Test Comic",
        format="Issue",
        issues_remaining=10,
        queue_position=1,
        status="active",
        is_test=True,
        user_id=user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    assert thread.is_test is True


@pytest.mark.asyncio
async def test_bulk_delete_test_data(client, db, enable_internal_ops):
    """Test bulk delete of test data."""
    user = db.execute(select(User).where(User.id == 1)).scalar_one_or_none()
    if user is None:
        user = User(id=1, username="test_user")
        db.add(user)
        db.commit()
        db.refresh(user)

    test_thread1 = Thread(
        title="Test Comic 1",
        format="Issue",
        issues_remaining=10,
        queue_position=1,
        status="active",
        is_test=True,
        user_id=user.id,
    )
    test_thread2 = Thread(
        title="Test Comic 2",
        format="Issue",
        issues_remaining=5,
        queue_position=2,
        status="active",
        is_test=True,
        user_id=user.id,
    )
    real_thread = Thread(
        title="Real Comic",
        format="Issue",
        issues_remaining=15,
        queue_position=3,
        status="active",
        is_test=False,
        user_id=user.id,
    )
    db.add_all([test_thread1, test_thread2, real_thread])
    db.commit()
    db.refresh(test_thread1)
    db.refresh(test_thread2)
    db.refresh(real_thread)

    session = SessionModel(
        started_at=datetime.now(UTC),
        ended_at=datetime.now(UTC),
        start_die=6,
        user_id=user.id,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    event1 = Event(
        type="roll",
        timestamp=datetime.now(UTC),
        die=6,
        result=5,
        selected_thread_id=test_thread1.id,
        selection_method="dice",
        session_id=session.id,
    )
    event2 = Event(
        type="rate",
        timestamp=datetime.now(UTC),
        rating=4.5,
        issues_read=1,
        queue_move="back",
        die_after=6,
        thread_id=test_thread2.id,
        session_id=session.id,
    )
    db.add_all([event1, event2])
    db.commit()

    response = await client.post("/api/admin/delete-test-data/")
    assert response.status_code == 200
    data = response.json()
    assert data["deleted_threads"] == 2
    assert data["deleted_events"] >= 2

    remaining_threads = db.execute(select(Thread).where(Thread.user_id == user.id)).scalars().all()
    assert len(remaining_threads) == 1
    assert remaining_threads[0].title == "Real Comic"


@pytest.mark.asyncio
async def test_export_csv_excludes_test_data(client, db, enable_internal_ops):
    """Test that CSV export excludes test data."""
    user = db.execute(select(User).where(User.id == 1)).scalar_one_or_none()
    if user is None:
        user = User(id=1, username="test_user")
        db.add(user)
        db.commit()
        db.refresh(user)

    test_thread = Thread(
        title="Test Comic",
        format="Issue",
        issues_remaining=10,
        queue_position=1,
        status="active",
        is_test=True,
        user_id=user.id,
    )
    real_thread = Thread(
        title="Real Comic",
        format="Issue",
        issues_remaining=15,
        queue_position=2,
        status="active",
        is_test=False,
        user_id=user.id,
    )
    db.add_all([test_thread, real_thread])
    db.commit()

    response = await client.get("/api/admin/export/csv/")
    assert response.status_code == 200

    content = response.content.decode("utf-8")
    lines = content.strip().split("\n")
    assert len(lines) == 2
    assert "Test Comic" not in content
    assert "Real Comic" in content


@pytest.mark.asyncio
async def test_export_json_excludes_test_data(client, db, enable_internal_ops):
    """Test that JSON export excludes test data."""
    import json

    user = db.execute(select(User).where(User.id == 1)).scalar_one_or_none()
    if user is None:
        user = User(id=1, username="test_user")
        db.add(user)
        db.commit()
        db.refresh(user)

    test_thread = Thread(
        title="Test Comic",
        format="Issue",
        issues_remaining=10,
        queue_position=1,
        status="active",
        is_test=True,
        user_id=user.id,
    )
    real_thread = Thread(
        title="Real Comic",
        format="Issue",
        issues_remaining=15,
        queue_position=2,
        status="active",
        is_test=False,
        user_id=user.id,
    )
    db.add_all([test_thread, real_thread])
    db.commit()

    response = await client.get("/api/admin/export/json/")
    assert response.status_code == 200

    data = json.loads(response.content.decode("utf-8"))
    assert len(data["threads"]) == 1
    assert data["threads"][0]["title"] == "Real Comic"


@pytest.mark.asyncio
async def test_export_summary_excludes_test_only_sessions(client, db, enable_internal_ops):
    """Test that session summary export excludes sessions with only test data."""
    user = db.execute(select(User).where(User.id == 1)).scalar_one_or_none()
    if user is None:
        user = User(id=1, username="test_user")
        db.add(user)
        db.commit()
        db.refresh(user)

    test_thread = Thread(
        title="Test Comic",
        format="Issue",
        issues_remaining=10,
        queue_position=1,
        status="active",
        is_test=True,
        user_id=user.id,
    )
    real_thread = Thread(
        title="Real Comic",
        format="Issue",
        issues_remaining=15,
        queue_position=2,
        status="active",
        is_test=False,
        user_id=user.id,
    )
    db.add_all([test_thread, real_thread])
    db.commit()
    db.refresh(test_thread)
    db.refresh(real_thread)

    test_session = SessionModel(
        started_at=datetime.now(UTC),
        ended_at=datetime.now(UTC),
        start_die=6,
        user_id=user.id,
    )
    real_session = SessionModel(
        started_at=datetime.now(UTC),
        ended_at=datetime.now(UTC),
        start_die=6,
        user_id=user.id,
    )
    db.add_all([test_session, real_session])
    db.commit()
    db.refresh(test_session)
    db.refresh(real_session)

    test_event = Event(
        type="rate",
        timestamp=datetime.now(UTC),
        rating=4.5,
        issues_read=1,
        queue_move="back",
        die_after=6,
        thread_id=test_thread.id,
        session_id=test_session.id,
    )
    real_event = Event(
        type="rate",
        timestamp=datetime.now(UTC),
        rating=5.0,
        issues_read=1,
        queue_move="front",
        die_after=6,
        thread_id=real_thread.id,
        session_id=real_session.id,
    )
    db.add_all([test_event, real_event])
    db.commit()

    response = await client.get("/api/admin/export/summary/")
    assert response.status_code == 200

    content = response.content.decode("utf-8")
    assert "Test Comic" not in content
    assert "Real Comic" in content


@pytest.mark.asyncio
async def test_delete_test_data_clears_pending_thread_id(client, db, enable_internal_ops):
    """Regression test for BUG-131: IntegrityError when deleting test thread with pending_thread_id.

    This test verifies that deleting test data that has sessions with pending_thread_id
    set does not cause a ForeignViolation error. The fix ensures that the UPDATE
    to clear pending_thread_id is flushed before the DELETE executes.
    """
    user = db.execute(select(User).where(User.id == 1)).scalar_one_or_none()
    if user is None:
        user = User(id=1, username="test_user")
        db.add(user)
        db.commit()
        db.refresh(user)

    test_thread = Thread(
        title="Test Comic",
        format="Issue",
        issues_remaining=10,
        queue_position=1,
        status="active",
        is_test=True,
        user_id=user.id,
    )
    db.add(test_thread)
    db.commit()
    db.refresh(test_thread)

    session = SessionModel(
        started_at=datetime.now(UTC),
        ended_at=None,
        start_die=6,
        user_id=user.id,
        pending_thread_id=test_thread.id,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    assert session.pending_thread_id == test_thread.id

    response = await client.post("/api/admin/delete-test-data/")

    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text if hasattr(response, 'text') else ''}"
    )

    db_thread = db.get(Thread, test_thread.id)
    assert db_thread is None

    db_session = db.get(SessionModel, session.id)
    if db_session:
        assert db_session.pending_thread_id is None
