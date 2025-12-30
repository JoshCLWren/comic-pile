"""API endpoint integration tests."""


import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_create_thread(client, db):
    """Test POST /threads/ creates new thread."""
    thread_data = {
        "title": "Spider-Man",
        "format": "Comic",
        "issues_remaining": 12,
    }
    response = await client.post("/threads/", json=thread_data)
    assert response.status_code == 201

    data = response.json()
    assert data["title"] == "Spider-Man"
    assert data["format"] == "Comic"
    assert data["issues_remaining"] == 12
    assert data["position"] == 1
    assert data["status"] == "active"
    assert "id" in data
    assert "created_at" in data

    from app.models import Thread

    thread = db.execute(select(Thread).where(Thread.title == "Spider-Man")).scalar_one_or_none()
    assert thread is not None
    assert thread.title == "Spider-Man"


@pytest.mark.asyncio
async def test_create_thread_validation(client):
    """Test POST /threads/ validates input."""
    invalid_data = {
        "title": "",
        "format": "Comic",
        "issues_remaining": 12,
    }
    response = await client.post("/threads/", json=invalid_data)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_threads(client, sample_data):
    """Test GET /threads/ returns all threads."""
    response = await client.get("/threads/")
    assert response.status_code == 200

    threads = response.json()
    assert len(threads) == 5
    assert threads[0]["title"] == "Superman"
    assert threads[1]["title"] == "Batman"
    assert threads[2]["title"] == "Wonder Woman"
    assert threads[3]["title"] == "Flash"
    assert threads[4]["title"] == "Aquaman"


@pytest.mark.asyncio
async def test_list_threads_empty(client):
    """Test GET /threads/ with no threads returns empty list."""
    response = await client.get("/threads/")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_thread(client, sample_data):
    """Test GET /threads/{id} returns single thread."""
    response = await client.get("/threads/1")
    assert response.status_code == 200

    thread = response.json()
    assert thread["id"] == 1
    assert thread["title"] == "Superman"
    assert thread["format"] == "Comic"
    assert thread["issues_remaining"] == 10
    assert thread["position"] == 1
    assert thread["status"] == "active"


@pytest.mark.asyncio
async def test_get_thread_not_found(client):
    """Test GET /threads/{id} returns 404 for non-existent thread."""
    response = await client.get("/threads/999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_thread(client, sample_data, db):
    """Test PUT /threads/{id} updates thread."""
    update_data = {
        "title": "Superman Updated",
        "format": "Trade Paperback",
        "issues_remaining": 8,
    }
    response = await client.put("/threads/1", json=update_data)
    assert response.status_code == 200

    thread = response.json()
    assert thread["id"] == 1
    assert thread["title"] == "Superman Updated"
    assert thread["format"] == "Trade Paperback"
    assert thread["issues_remaining"] == 8

    from app.models import Thread

    db_thread = db.get(Thread, 1)
    assert db_thread.title == "Superman Updated"
    assert db_thread.format == "Trade Paperback"
    assert db_thread.issues_remaining == 8


@pytest.mark.asyncio
async def test_update_thread_partial(client, sample_data):
    """Test PUT /threads/{id} with partial data."""
    update_data = {
        "title": "Batman Updated",
    }
    response = await client.put("/threads/2", json=update_data)
    assert response.status_code == 200

    thread = response.json()
    assert thread["title"] == "Batman Updated"
    assert thread["format"] == "Comic"
    assert thread["issues_remaining"] == 5


@pytest.mark.asyncio
async def test_update_thread_not_found(client):
    """Test PUT /threads/{id} returns 404 for non-existent thread."""
    update_data = {
        "title": "Non-existent",
    }
    response = await client.put("/threads/999", json=update_data)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_thread_complete_status(client, sample_data, db):
    """Test PUT /threads/{id} sets completed status when issues_remaining is 0."""
    update_data = {
        "issues_remaining": 0,
    }
    response = await client.put("/threads/1", json=update_data)
    assert response.status_code == 200

    thread = response.json()
    assert thread["status"] == "completed"
    assert thread["issues_remaining"] == 0

    from app.models import Thread

    db_thread = db.get(Thread, 1)
    assert db_thread.status == "completed"


@pytest.mark.asyncio
async def test_update_thread_active_status(client, sample_data, db):
    """Test PUT /threads/{id} sets active status when issues_remaining > 0."""
    update_data = {
        "issues_remaining": 5,
    }
    response = await client.put("/threads/3", json=update_data)
    assert response.status_code == 200

    thread = response.json()
    assert thread["status"] == "active"
    assert thread["issues_remaining"] == 5

    from app.models import Thread

    db_thread = db.get(Thread, 3)
    assert db_thread.status == "active"


@pytest.mark.asyncio
async def test_delete_thread(client, sample_data, db):
    """Test DELETE /threads/{id} removes thread."""
    response = await client.delete("/threads/1")
    assert response.status_code == 204

    from app.models import Thread

    db_thread = db.get(Thread, 1)
    assert db_thread is None

    response = await client.get("/threads/1")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_thread_not_found(client):
    """Test DELETE /threads/{id} returns 404 for non-existent thread."""
    response = await client.delete("/threads/999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_session_current(client, sample_data):
    """Test GET /session/current/ returns active session."""
    from app.models import Session as SessionModel

    session = SessionModel(id=1, start_die=6, user_id=1)
    sample_data["db"].add(session)
    sample_data["db"].commit()

    response = await client.get("/sessions/current/")
    assert response.status_code == 200

    session = response.json()
    assert session["id"] == 1
    assert session["start_die"] == 6
    assert session["user_id"] == 1
    assert "ladder_path" in session


@pytest.mark.asyncio
async def test_get_session_current_not_found(client):
    """Test GET /session/current/ returns 404 when no active session."""
    response = await client.get("/sessions/current/")
    assert response.status_code == 404
    assert "no active session" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_sessions(client, sample_data):
    """Test GET /sessions/ lists all sessions."""
    response = await client.get("/sessions/")
    assert response.status_code == 200

    sessions = response.json()
    assert len(sessions) == 2
    assert sessions[0]["start_die"] == 8
    assert sessions[1]["start_die"] == 6


@pytest.mark.asyncio
async def test_get_sessions_pagination(client, sample_data):
    """Test GET /sessions/ with pagination."""
    response = await client.get("/sessions/?limit=1&offset=0")
    assert response.status_code == 200

    sessions = response.json()
    assert len(sessions) == 1


@pytest.mark.asyncio
async def test_get_session(client, sample_data):
    """Test GET /sessions/{id} returns single session."""
    response = await client.get("/sessions/1")
    assert response.status_code == 200

    session = response.json()
    assert session["id"] == 1
    assert session["start_die"] == 6
    assert session["user_id"] == 1
    assert "ladder_path" in session


@pytest.mark.asyncio
async def test_get_session_not_found(client):
    """Test GET /sessions/{id} returns 404 for non-existent session."""
    response = await client.get("/sessions/999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_session_details(client, sample_data):
    """Test GET /sessions/{id}/details returns events."""
    response = await client.get("/sessions/1/details")
    assert response.status_code == 200

    content = response.text
    assert "roll" in content
    assert "rate" in content
    assert "Superman" in content
