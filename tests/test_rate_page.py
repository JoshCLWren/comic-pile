"""Integration tests for rate.html page interactive elements."""

import pytest

from app.models import Event, Session as SessionModel, Thread


@pytest.mark.asyncio
async def test_rate_page_renders(client):
    """GET /rate returns 200 and renders HTML."""
    response = await client.get("/rate", follow_redirects=True)
    assert response.status_code == 200
    assert "<!DOCTYPE html>" in response.text
    assert "Rate Session" in response.text


@pytest.mark.asyncio
async def test_rate_page_contains_rating_input(client):
    """Rate page contains rating slider input."""
    response = await client.get("/rate", follow_redirects=True)
    assert response.status_code == 200
    html = response.text
    assert 'id="rating-input"' in html
    assert 'type="range"' in html
    assert 'min="0.5"' in html
    assert 'max="5.0"' in html
    assert 'step="0.5"' in html


@pytest.mark.asyncio
async def test_rate_page_contains_submit_button(client):
    """Rate page contains Save & Continue button."""
    response = await client.get("/rate", follow_redirects=True)
    assert response.status_code == 200
    html = response.text
    assert 'id="submit-btn"' in html
    assert "Save & Continue" in html
    assert 'onclick="submitRating(false)"' in html


@pytest.mark.asyncio
async def test_rate_page_contains_finish_button(client):
    """Rate page contains Finish Session button."""
    response = await client.get("/rate", follow_redirects=True)
    assert response.status_code == 200
    html = response.text
    assert 'id="finish-btn"' in html
    assert "Finish Session" in html
    assert 'onclick="submitRating(true)"' in html


@pytest.mark.asyncio
async def test_rate_page_contains_thread_info(client, db, sample_data):
    """Rate page displays thread info when active session exists."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=10, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=3,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    db.add(event)
    db.commit()

    response = await client.get("/rate", follow_redirects=True)
    assert response.status_code == 200
    html = response.text
    assert 'id="thread-info"' in html


@pytest.mark.asyncio
async def test_rate_page_contains_session_safe_indicator(client, db, sample_data):
    """Rate page contains session safe indicator element."""
    response = await client.get("/rate", follow_redirects=True)
    assert response.status_code == 200
    html = response.text
    assert 'id="session-safe-indicator"' in html


@pytest.mark.asyncio
async def test_rate_page_contains_dice_preview(client, db, sample_data):
    """Rate page contains dice preview element."""
    response = await client.get("/rate", follow_redirects=True)
    assert response.status_code == 200
    html = response.text
    assert 'id="die-preview"' in html
    assert 'id="die-preview-wrapper"' in html


@pytest.mark.asyncio
async def test_rate_page_contains_queue_effect_text(client):
    """Rate page contains queue effect text display."""
    response = await client.get("/rate", follow_redirects=True)
    assert response.status_code == 200
    html = response.text
    assert 'id="queue-effect"' in html


@pytest.mark.asyncio
async def test_rate_page_contains_error_message(client):
    """Rate page contains error message element (hidden by default)."""
    response = await client.get("/rate", follow_redirects=True)
    assert response.status_code == 200
    html = response.text
    assert 'id="error-message"' in html
    assert 'class="text-xs text-rose-500 text-center font-bold hidden"' in html


@pytest.mark.asyncio
async def test_rate_page_contains_rating_value_display(client):
    """Rate page contains rating value display."""
    response = await client.get("/rate", follow_redirects=True)
    assert response.status_code == 200
    html = response.text
    assert 'id="rating-value"' in html


@pytest.mark.asyncio
async def test_rate_page_contains_header_dice_container(client):
    """Rate page contains header dice container."""
    response = await client.get("/rate", follow_redirects=True)
    assert response.status_code == 200
    html = response.text
    assert 'id="header-die-container"' in html
    assert 'id="header-die-state-label"' in html


@pytest.mark.asyncio
async def test_rate_page_javascript_dice_ladder_constant(client):
    """Rate page JavaScript contains DICE_LADDER constant."""
    response = await client.get("/rate", follow_redirects=True)
    assert response.status_code == 200
    html = response.text
    assert "DICE_LADDER" in html
    assert "[4, 6, 8, 10, 12, 20]" in html


@pytest.mark.asyncio
async def test_rate_page_javascript_updateui_function(client):
    """Rate page JavaScript contains updateUI function."""
    response = await client.get("/rate", follow_redirects=True)
    assert response.status_code == 200
    html = response.text
    assert "function updateUI(val)" in html


@pytest.mark.asyncio
async def test_rate_page_javascript_submitrating_function(client):
    """Rate page JavaScript contains submitRating function."""
    response = await client.get("/rate", follow_redirects=True)
    assert response.status_code == 200
    html = response.text
    assert "async function submitRating(finishSession)" in html


@pytest.mark.asyncio
async def test_rate_page_javascript_checkrestorepoint_function(client):
    """Rate page JavaScript contains checkRestorePointBeforeSubmit function."""
    response = await client.get("/rate", follow_redirects=True)
    assert response.status_code == 200
    html = response.text
    assert "async function checkRestorePointBeforeSubmit()" in html


@pytest.mark.asyncio
async def test_rate_session_api_returns_thread_info(client, db):
    """GET /sessions/current/ returns active thread info for rate page."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=10, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Amazing Spider-Man",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=4,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    db.add(event)
    db.commit()

    response = await client.get("/sessions/current/")
    assert response.status_code == 200
    data = response.json()
    assert "active_thread" in data
    assert data["active_thread"]["id"] == thread.id
    assert data["active_thread"]["title"] == "Amazing Spider-Man"
    assert data["active_thread"]["format"] == "Comic"
    assert data["active_thread"]["issues_remaining"] == 10


@pytest.mark.asyncio
async def test_rate_session_api_returns_die_info(client, db):
    """GET /sessions/current/ returns die info for dice preview."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=10, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=3,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    db.add(event)
    db.commit()

    response = await client.get("/sessions/current/")
    assert response.status_code == 200
    data = response.json()
    assert "current_die" in data
    assert data["current_die"] == 10
    assert "last_rolled_result" in data
    assert data["last_rolled_result"] == 3


@pytest.mark.asyncio
async def test_rate_session_api_returns_has_restore_point(client, db):
    """GET /sessions/current/ returns has_restore_point for session safe indicator."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=10, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    db.add(event)
    db.commit()

    response = await client.get("/sessions/current/")
    assert response.status_code == 200
    data = response.json()
    assert "has_restore_point" in data
    assert isinstance(data["has_restore_point"], bool)


@pytest.mark.asyncio
async def test_rate_api_invalid_rating(client, db, sample_data):
    """POST /rate/ with invalid rating returns 400 error."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=10, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = sample_data["threads"][0]
    db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    db.add(event)
    db.commit()

    response = await client.post("/rate/", json={"rating": 6.0, "issues_read": 1})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_rate_api_low_rating_moves_to_back(client, db):
    """POST /rate/ with rating < 4.0 moves thread to back of queue."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=10, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    thread1 = Thread(
        title="Comic 1",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    thread2 = Thread(
        title="Comic 2",
        format="Comic",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    db.add(thread1)
    db.add(thread2)
    db.commit()
    db.refresh(thread1)
    db.refresh(thread2)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread1.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread1.id,
    )
    db.add(event)
    db.commit()

    await client.post("/rate/", json={"rating": 3.0, "issues_read": 1})

    db.refresh(thread1)
    db.refresh(thread2)
    assert thread1.queue_position > thread2.queue_position


@pytest.mark.asyncio
async def test_rate_api_high_rating_moves_to_front(client, db):
    """POST /rate/ with rating >= 4.0 moves thread to front of queue."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=10, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    thread1 = Thread(
        title="Comic 1",
        format="Comic",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    thread2 = Thread(
        title="Comic 2",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(thread1)
    db.add(thread2)
    db.commit()
    db.refresh(thread1)
    db.refresh(thread2)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread1.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread1.id,
    )
    db.add(event)
    db.commit()

    await client.post("/rate/", json={"rating": 4.0, "issues_read": 1})

    db.refresh(thread1)
    db.refresh(thread2)
    assert thread1.queue_position < thread2.queue_position


@pytest.mark.asyncio
async def test_rate_api_updates_last_activity_at(client, db):
    """POST /rate/ updates thread last_activity_at timestamp."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=10, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    old_activity_at = thread.last_activity_at

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    db.add(event)
    db.commit()

    await client.post("/rate/", json={"rating": 4.0, "issues_read": 1})

    db.refresh(thread)
    assert thread.last_activity_at is not None
    if old_activity_at:
        assert thread.last_activity_at > old_activity_at


@pytest.mark.asyncio
async def test_rate_api_creates_snapshot(client, db):
    """POST /rate/ creates snapshot for undo functionality."""
    from tests.conftest import get_or_create_user

    from app.models import Snapshot
    from sqlalchemy import select

    user = get_or_create_user(db)

    session = SessionModel(start_die=10, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    db.add(event)
    db.commit()

    await client.post("/rate/", json={"rating": 4.5, "issues_read": 1})

    snapshots = (
        db.execute(select(Snapshot).where(Snapshot.session_id == session.id)).scalars().all()
    )
    assert len(snapshots) >= 1
    assert any("4.5" in s.description for s in snapshots)


@pytest.mark.asyncio
async def test_rate_page_without_active_session(client, db):
    """Rate page renders correctly when no active session exists."""
    response = await client.get("/rate", follow_redirects=True)
    assert response.status_code == 200
    html = response.text
    assert "Rate Session" in html


@pytest.mark.asyncio
async def test_rate_api_with_min_rating(client, db):
    """POST /rate/ accepts minimum rating value (0.5)."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=10, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    db.add(event)
    db.commit()

    response = await client.post("/rate/", json={"rating": 0.5, "issues_read": 1})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_rate_api_with_max_rating(client, db):
    """POST /rate/ accepts maximum rating value (5.0)."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=10, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    db.add(event)
    db.commit()

    response = await client.post("/rate/", json={"rating": 5.0, "issues_read": 1})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_rate_api_clears_pending_thread(client, db):
    """POST /rate/ clears pending_thread_id from session."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    thread = Thread(
        title="Test Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    session = SessionModel(start_die=10, user_id=user.id, pending_thread_id=thread.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    db.add(event)
    db.commit()

    await client.post("/rate/", json={"rating": 4.0, "issues_read": 1})

    db.refresh(session)
    assert session.pending_thread_id is None


@pytest.mark.asyncio
async def test_rate_api_updates_issues_remaining(client, db):
    """POST /rate/ correctly decreases issues_remaining."""
    from tests.conftest import get_or_create_user

    user = get_or_create_user(db)

    session = SessionModel(start_die=10, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)

    thread = Thread(
        title="Test Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    db.add(event)
    db.commit()

    response = await client.post("/rate/", json={"rating": 4.0, "issues_read": 2})
    assert response.status_code == 200

    data = response.json()
    assert data["issues_remaining"] == 3

    db.refresh(thread)
    assert thread.issues_remaining == 3


@pytest.mark.asyncio
async def test_rate_page_contains_explosion_layer(client):
    """Rate page contains explosion layer for visual effects."""
    response = await client.get("/rate", follow_redirects=True)
    assert response.status_code == 200
    html = response.text
    assert 'id="explosion-layer"' in html
