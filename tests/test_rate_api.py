"""Tests for rate API endpoints."""

import pytest
from sqlalchemy import select

from app.models import Event, Thread
from httpx import AsyncClient
from app.models import Session as SessionModel
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_rate_success(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """POST /rate/ updates thread correctly."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    response = await auth_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 200

    data = response.json()
    assert data["issues_remaining"] == 4
    assert data["last_rating"] == 4.0

    await async_db.refresh(thread)
    assert thread.issues_remaining == 4
    assert thread.last_rating == 4.0


@pytest.mark.asyncio
async def test_rate_low_rating(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """Rating=3.0, die_size steps up."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    response = await auth_client.post("/api/rate/", json={"rating": 3.0, "issues_read": 1})
    assert response.status_code == 200

    result = await async_db.execute(
        select(Event).where(Event.session_id == session.id).where(Event.type == "rate")
    )
    events = result.scalars().all()
    assert len(events) == 1
    assert events[0].die_after == 12


@pytest.mark.asyncio
async def test_rate_high_rating(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """Rating=4.0, die_size steps down."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    response = await auth_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 200

    result = await async_db.execute(
        select(Event).where(Event.session_id == session.id).where(Event.type == "rate")
    )
    events = result.scalars().all()
    assert len(events) == 1
    assert events[0].die_after == 8


@pytest.mark.asyncio
async def test_rate_completes_thread(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """Issues <= 0, moves to back of queue, session ends only with finish_session=True."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    response = await auth_client.post(
        "/api/rate/", json={"rating": 4.0, "issues_read": 1, "finish_session": True}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "completed"
    assert data["issues_remaining"] == 0

    await async_db.refresh(thread)
    assert thread.status == "completed"
    assert thread.queue_position == 1

    await async_db.refresh(session)
    assert session.ended_at is not None


@pytest.mark.asyncio
async def test_rate_finish_session_no_missing_greenlet_after_queue_commit(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """finish_session path should not access expired thread attrs after queue move commit."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    target_thread = Thread(
        title="Target Thread",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    other_thread = Thread(
        title="Other Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    async_db.add_all([target_thread, other_thread])
    await async_db.commit()
    await async_db.refresh(target_thread)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=target_thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=target_thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    response = await auth_client.post(
        "/api/rate/",
        json={"rating": 4.0, "issues_read": 1, "finish_session": True},
    )
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "completed"
    assert data["issues_remaining"] == 0


@pytest.mark.asyncio
async def test_rate_records_event(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """Event saved with rating and issues_read."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    response = await auth_client.post("/api/rate/", json={"rating": 4.5, "issues_read": 2})
    assert response.status_code == 200

    result = await async_db.execute(
        select(Event).where(Event.session_id == session.id).where(Event.type == "rate")
    )
    events = result.scalars().all()
    assert len(events) == 1
    assert events[0].rating == 4.5
    assert events[0].issues_read == 2


@pytest.mark.asyncio
async def test_rate_no_active_session(auth_client: AsyncClient) -> None:
    """Returns error if no active session."""
    response = await auth_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 400
    assert "No active session" in response.json()["detail"]


@pytest.mark.asyncio
async def test_rate_no_active_thread(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """Returns error if no active thread in session."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    response = await auth_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 400
    assert "No active thread" in response.json()["detail"]


@pytest.mark.asyncio
async def test_rate_updates_manual_die(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """Rating creates rate event with die_after value."""
    from tests.conftest import get_or_create_user_async
    from comic_pile.session import get_current_die

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, manual_die=20, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        die=20,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    response = await auth_client.post("/api/rate/", json={"rating": 4.0, "issues_read": 1})
    assert response.status_code == 200

    await async_db.refresh(session)
    manual_die = session.manual_die
    assert manual_die == 20

    result = await async_db.execute(
        select(Event)
        .where(Event.session_id == session.id)
        .where(Event.type == "rate")
        .order_by(Event.timestamp.desc())
    )
    rate_event = result.scalars().first()
    assert rate_event is not None
    assert rate_event.die == 20
    assert rate_event.die_after == 12

    current_die = await get_current_die(session.id, async_db)
    assert current_die == 12


@pytest.mark.asyncio
async def test_rate_low_rating_updates_manual_die(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Low rating steps die up and records die_after in rate event."""
    from tests.conftest import get_or_create_user_async
    from comic_pile.session import get_current_die

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=6, manual_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        die=6,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    response = await auth_client.post("/api/rate/", json={"rating": 3.0, "issues_read": 1})
    assert response.status_code == 200

    await async_db.refresh(session)
    manual_die = session.manual_die
    assert manual_die == 6

    result = await async_db.execute(
        select(Event)
        .where(Event.session_id == session.id)
        .where(Event.type == "rate")
        .order_by(Event.timestamp.desc())
    )
    rate_event = result.scalars().first()
    assert rate_event is not None
    assert rate_event.die == 6
    assert rate_event.die_after == 8

    current_die = await get_current_die(session.id, async_db)
    assert current_die == 8


@pytest.mark.asyncio
async def test_rate_finish_session_flag_controls_session_end(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """finish_session=False keeps session active even when thread completes."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    response = await auth_client.post(
        "/api/rate/", json={"rating": 4.0, "issues_read": 1, "finish_session": False}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "completed"
    assert data["issues_remaining"] == 0

    await async_db.refresh(thread)
    assert thread.status == "completed"

    await async_db.refresh(session)
    assert session.ended_at is None


def test_rating_settings_returns_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test rating settings return default values."""
    from app.config import clear_settings_cache, get_rating_settings

    # Clear any cached settings and env vars
    for var in ["RATING_MIN", "RATING_MAX", "RATING_THRESHOLD"]:
        monkeypatch.delenv(var, raising=False)
    clear_settings_cache()

    settings = get_rating_settings()
    assert settings.rating_min == 0.5
    assert settings.rating_max == 5.0
    assert settings.rating_threshold == 4.0


def test_rating_settings_returns_custom_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test rating settings return custom values when set."""
    from app.config import clear_settings_cache, get_rating_settings

    monkeypatch.setenv("RATING_MIN", "1.0")
    monkeypatch.setenv("RATING_MAX", "4.5")
    monkeypatch.setenv("RATING_THRESHOLD", "3.5")
    clear_settings_cache()

    settings = get_rating_settings()
    assert settings.rating_min == 1.0
    assert settings.rating_max == 4.5
    assert settings.rating_threshold == 3.5


def test_rating_settings_validates_range(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test rating settings validate and clamp to valid range."""
    from app.config import clear_settings_cache, get_rating_settings

    # Values outside range get clamped by validators
    monkeypatch.setenv("RATING_MIN", "10.0")
    monkeypatch.setenv("RATING_MAX", "15.0")
    monkeypatch.setenv("RATING_THRESHOLD", "-1.0")
    clear_settings_cache()

    settings = get_rating_settings()
    # Validators clamp out-of-range values to defaults
    assert settings.rating_min == 0.5
    assert settings.rating_max == 5.0
    assert settings.rating_threshold == 4.0


@pytest.mark.asyncio
async def test_rate_with_snoozed_thread_ids_no_missing_greenlet(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data: dict
) -> None:
    """Regression test for MissingGreenlet error when accessing snoozed_thread_ids after commit.

    This test ensures that accessing session.snoozed_thread_ids doesn't trigger
    a lazy load after commit, which causes MissingGreenlet in SQLAlchemy async.
    """
    threads = sample_data["threads"]

    # Create a session
    session = SessionModel(
        user_id=1,
        start_die=20,
        manual_die=None,
        snoozed_thread_ids=[threads[0].id],
    )
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    # Create a roll event
    event = Event(
        type="roll",
        session_id=session.id,
        thread_id=threads[1].id,
        selected_thread_id=threads[1].id,
    )
    async_db.add(event)
    await async_db.commit()

    # Rate the thread - this should not raise MissingGreenlet
    response = await auth_client.post(
        "/api/rate/",
        json={"rating": 4.0, "issues_read": 1, "finish_session": False},
    )
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == threads[1].id

    # Verify session still has snoozed_thread_ids accessible
    await async_db.refresh(session)
    assert session.snoozed_thread_ids == [threads[0].id]


@pytest.mark.asyncio
async def test_rate_final_issue_completes_thread_but_keeps_session_active(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Rating the final issue should complete the thread even if finish_session=False."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Final Issue Thread",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    # Simulate a roll event
    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    # Rate with finish_session=False
    response = await auth_client.post(
        "/api/rate/", json={"rating": 4.0, "issues_read": 1, "finish_session": False}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "completed"
    assert data["issues_remaining"] == 0

    await async_db.refresh(thread)
    assert thread.status == "completed"

    await async_db.refresh(session)
    assert session.ended_at is None
    assert session.pending_thread_id is None


@pytest.mark.asyncio
async def test_finish_session_ends_session_regardless_of_thread_completion(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Explicit finish_session=True should end the session even if thread is not completed."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Ongoing Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    # Simulate a roll event
    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    # Rate with finish_session=True
    response = await auth_client.post(
        "/api/rate/", json={"rating": 4.0, "issues_read": 1, "finish_session": True}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "active"  # Still active because issues_remaining > 0
    assert data["issues_remaining"] == 4

    await async_db.refresh(session)
    assert session.ended_at is not None
