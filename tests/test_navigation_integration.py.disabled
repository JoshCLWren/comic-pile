"""Integration tests for navigation and global modals."""

import pytest
from sqlalchemy import select

from app.models import Thread
from app.models import Session as SessionModel


@pytest.mark.asyncio
async def test_roll_page_navigation(client):
    """Test GET / returns roll page with 200 status."""
    response = await client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_roll_page_explicit_navigation(client):
    """Test GET /roll returns roll page with 200 status."""
    response = await client.get("/roll")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_rate_page_navigation(client):
    """Test GET /rate returns rate page with 200 status."""
    response = await client.get("/rate")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_queue_page_navigation(client):
    """Test GET /queue returns queue page with 200 status."""
    response = await client.get("/queue")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_history_page_navigation(client):
    """Test GET /history returns history page with 200 status."""
    response = await client.get("/history")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_navigation_all_pages(client):
    """Verify all main navigation pages return 200 and render HTML."""
    pages = ["/", "/roll", "/rate", "/queue", "/history"]

    for page in pages:
        response = await client.get(page)
        assert response.status_code == 200, f"Page {page} failed"
        assert "text/html" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_add_thread_modal_valid(client, db):
    """Test POST /threads/ creates new thread via modal."""
    thread_data = {
        "title": "X-Men",
        "format": "TPB",
        "issues_remaining": 6,
    }
    response = await client.post("/threads/", json=thread_data)
    assert response.status_code == 201

    data = response.json()
    assert data["title"] == "X-Men"
    assert data["format"] == "TPB"
    assert data["issues_remaining"] == 6
    assert data["status"] == "active"

    thread = db.execute(select(Thread).where(Thread.title == "X-Men")).scalar_one_or_none()
    assert thread is not None
    assert thread.issues_remaining == 6


@pytest.mark.asyncio
async def test_add_thread_modal_different_formats(client, db):
    """Test creating threads with different formats."""
    formats = ["TPB", "Issue", "Graphic Novel"]

    for format_type in formats:
        thread_data = {
            "title": f"Test Comic {format_type}",
            "format": format_type,
            "issues_remaining": 5,
        }
        response = await client.post("/threads/", json=thread_data)
        assert response.status_code == 201

        data = response.json()
        assert data["format"] == format_type


@pytest.mark.asyncio
async def test_add_thread_modal_various_issues(client, db):
    """Test creating threads with various issues remaining values."""
    issues_values = [1, 5, 10, 50, 100]

    for issues in issues_values:
        thread_data = {
            "title": f"Test Comic {issues} issues",
            "format": "TPB",
            "issues_remaining": issues,
        }
        response = await client.post("/threads/", json=thread_data)
        assert response.status_code == 201

        data = response.json()
        assert data["issues_remaining"] == issues


@pytest.mark.asyncio
async def test_add_thread_modal_empty_title_fails_validation(client):
    """Test POST /threads/ with empty title fails validation."""
    invalid_data = {
        "title": "",
        "format": "TPB",
        "issues_remaining": 6,
    }
    response = await client.post("/threads/", json=invalid_data)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_add_thread_modal_missing_format_fails_validation(client):
    """Test POST /threads/ with missing format fails validation."""
    invalid_data = {
        "title": "Test Comic",
        "issues_remaining": 6,
    }
    response = await client.post("/threads/", json=invalid_data)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_add_thread_modal_invalid_issues_fails_validation(client):
    """Test POST /threads/ with invalid issues remaining fails validation."""
    invalid_data = {
        "title": "Test Comic",
        "format": "TPB",
        "issues_remaining": -1,
    }
    response = await client.post("/threads/", json=invalid_data)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reactivate_completed_thread_modal(client, db, sample_data):
    """Test POST /threads/reactivate reactivates completed thread."""
    completed_thread = sample_data["threads"][2]
    assert completed_thread.status == "completed"

    reactivate_data = {
        "thread_id": completed_thread.id,
        "issues_to_add": 5,
    }
    response = await client.post("/threads/reactivate", json=reactivate_data)
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "active"
    assert data["issues_remaining"] == 5
    assert data["position"] == 1

    db.refresh(completed_thread)
    assert completed_thread.status == "active"
    assert completed_thread.issues_remaining == 5
    assert completed_thread.queue_position == 1


@pytest.mark.asyncio
async def test_reactive_thread_updates_issues_remaining(client, db, sample_data):
    """Test reactivation updates issues remaining correctly."""
    completed_thread = sample_data["threads"][2]

    reactivate_data = {
        "thread_id": completed_thread.id,
        "issues_to_add": 12,
    }
    response = await client.post("/threads/reactivate", json=reactivate_data)
    assert response.status_code == 200

    data = response.json()
    assert data["issues_remaining"] == 12

    db.refresh(completed_thread)
    assert completed_thread.issues_remaining == 12


@pytest.mark.asyncio
async def test_reactive_nonexistent_thread_returns_404(client, db):
    """Test POST /threads/reactivate with non-existent thread returns 404."""
    reactivate_data = {
        "thread_id": 99999,
        "issues_to_add": 5,
    }
    response = await client.post("/threads/reactivate", json=reactivate_data)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_reactivate_already_active_thread_fails(client, db, sample_data):
    """Test POST /threads/reactivate on already active thread fails."""
    active_thread = sample_data["threads"][0]
    assert active_thread.status == "active"

    reactivate_data = {
        "thread_id": active_thread.id,
        "issues_to_add": 5,
    }
    response = await client.post("/threads/reactivate", json=reactivate_data)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_reactivate_with_zero_issues_fails(client, db, sample_data):
    """Test POST /threads/reactivate with 0 issues fails validation."""
    completed_thread = sample_data["threads"][2]

    reactivate_data = {
        "thread_id": completed_thread.id,
        "issues_to_add": 0,
    }
    response = await client.post("/threads/reactivate", json=reactivate_data)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_override_roll_modal(client, db, sample_data):
    """Test POST /roll/override selects a thread."""
    active_thread = sample_data["threads"][0]

    override_data = {
        "thread_id": active_thread.id,
    }
    response = await client.post("/roll/override", json=override_data)
    assert response.status_code == 200

    data = response.json()
    assert data["thread_id"] == active_thread.id
    assert data["title"] == active_thread.title


@pytest.mark.asyncio
async def test_override_roll_nonexistent_thread_returns_404(client, db):
    """Test POST /roll/override with non-existent thread returns 404."""
    override_data = {
        "thread_id": 99999,
    }
    response = await client.post("/roll/override", json=override_data)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_404_error_page(client):
    """Test GET to non-existent page returns 404 page."""
    response = await client.get("/this-page-does-not-exist", headers={"accept": "text/html"})
    assert response.status_code == 404

    content = response.text
    assert "404" in content
    assert "Not Found" in content


@pytest.mark.asyncio
async def test_404_page_contains_home_link(client):
    """Test 404 page contains helpful navigation link to home."""
    response = await client.get("/non-existent-route", headers={"accept": "text/html"})
    assert response.status_code == 404

    content = response.text
    assert 'href="/"' in content


@pytest.mark.asyncio
async def test_404_status_code_is_correct(client):
    """Test 404 error returns correct status code."""
    response = await client.get("/some-random-path-12345")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_navigation_flow_roll_to_rate_to_queue_to_history(client):
    """Test full navigation flow: roll -> rate -> queue -> history."""
    pages = ["/roll", "/rate", "/queue", "/history"]

    for page in pages:
        response = await client.get(page)
        assert response.status_code == 200, f"Navigation to {page} failed"


@pytest.mark.asyncio
async def test_session_persists_across_pages(client, db):
    """Test session persists when navigating between pages."""
    first_response = await client.get("/")
    assert first_response.status_code == 200

    session_count = db.execute(select(SessionModel)).scalar()
    assert session_count is not None

    await client.get("/rate")
    await client.get("/queue")

    session_count_after = db.execute(select(SessionModel)).scalar()
    assert session_count_after is not None


@pytest.mark.asyncio
async def test_navigation_back_to_roll(client):
    """Test navigation back to roll page from other pages."""
    pages = ["/rate", "/queue", "/history"]

    for page in pages:
        response = await client.get(page)
        assert response.status_code == 200

        roll_response = await client.get("/roll")
        assert roll_response.status_code == 200


@pytest.mark.asyncio
async def test_navigation_with_active_session(client, db, sample_data):
    """Test navigation works correctly with an active session."""
    session = sample_data["sessions"][0]
    assert session.ended_at is None

    pages = ["/", "/roll", "/rate", "/queue", "/history"]

    for page in pages:
        response = await client.get(page)
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_base_template_includes_navigation(client):
    """Test that base template includes navigation elements."""
    response = await client.get("/")
    assert response.status_code == 200

    content = response.text
    assert "nav-container" in content
    assert "Roll" in content or "🎲" in content
    assert "Rate" in content or "📝" in content
    assert "Queue" in content or "📚" in content
    assert "History" in content or "📜" in content


@pytest.mark.asyncio
async def test_base_template_includes_modals(client):
    """Test that base template includes modal structures."""
    response = await client.get("/")
    assert response.status_code == 200

    content = response.text
    assert "add-thread-modal" in content
    assert "reactivate-modal" in content
    assert "override-modal" in content
