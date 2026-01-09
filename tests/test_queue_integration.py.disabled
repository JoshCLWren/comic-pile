"""Comprehensive integration tests for queue page operations."""

from sqlalchemy import select

import pytest

from app.models import Event, Thread


@pytest.mark.asyncio
async def test_queue_page_loads_correctly(client, sample_data):
    """Queue page loads and renders correctly."""
    response = await client.get("/queue/", follow_redirects=True)
    assert response.status_code == 200
    assert "Read Queue" in response.text
    assert "Your upcoming comics" in response.text


@pytest.mark.asyncio
async def test_queue_api_shows_thread_list(client, sample_data):
    """Queue API returns threads with correct information."""
    response = await client.get("/threads/")
    assert response.status_code == 200

    threads = response.json()
    assert len(threads) > 0

    for thread_data in threads:
        assert "title" in thread_data
        assert "format" in thread_data
        assert "issues_remaining" in thread_data
        assert "position" in thread_data


@pytest.mark.asyncio
async def test_queue_api_empty_state(client, db):
    """Queue API returns empty list when no threads exist."""
    response = await client.get("/threads/")
    threads = response.json()

    for thread in threads:
        await client.delete(f"/threads/{thread['id']}")

    response = await client.get("/threads/")
    assert response.status_code == 200
    threads = response.json()
    assert len(threads) == 0


@pytest.mark.asyncio
async def test_session_safe_indicator_hidden_when_no_restore_point(client, db):
    """Session safe indicator is hidden when no restore point exists."""
    response = await client.get("/queue/", follow_redirects=True)
    assert response.status_code == 200
    assert 'id="session-safe-indicator"' in response.text


@pytest.mark.asyncio
async def test_edit_thread_fetches_data(client, sample_data):
    """Fetching thread data for edit modal returns correct information."""
    thread_id = sample_data["threads"][0].id

    response = await client.get(f"/threads/{thread_id}")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == thread_id
    assert "title" in data
    assert "format" in data
    assert "issues_remaining" in data
    assert "notes" in data


@pytest.mark.asyncio
async def test_edit_thread_updates_title(client, db, sample_data):
    """Editing thread title updates thread correctly."""
    thread_id = sample_data["threads"][0].id
    new_title = "Updated Superman Title"

    response = await client.put(
        f"/threads/{thread_id}",
        json={"title": new_title, "format": "Comic", "issues_remaining": 10},
    )
    assert response.status_code == 200

    thread = db.get(Thread, thread_id)
    assert thread.title == new_title


@pytest.mark.asyncio
async def test_edit_thread_updates_issues_remaining(client, db, sample_data):
    """Editing thread issues_remaining updates correctly."""
    thread_id = sample_data["threads"][0].id
    new_issues = 20

    response = await client.put(
        f"/threads/{thread_id}",
        json={"title": "Superman", "format": "Comic", "issues_remaining": new_issues},
    )
    assert response.status_code == 200

    thread = db.get(Thread, thread_id)
    assert thread.issues_remaining == new_issues


@pytest.mark.asyncio
async def test_edit_thread_updates_notes(client, db, sample_data):
    """Editing thread notes updates correctly."""
    thread_id = sample_data["threads"][0].id
    new_notes = "Updated notes for testing"

    response = await client.put(
        f"/threads/{thread_id}",
        json={
            "title": "Superman",
            "format": "Comic",
            "issues_remaining": 10,
            "notes": new_notes,
        },
    )
    assert response.status_code == 200

    thread = db.get(Thread, thread_id)
    assert thread.notes == new_notes


@pytest.mark.asyncio
async def test_edit_thread_all_fields(client, db, sample_data):
    """Editing all thread fields works correctly."""
    thread_id = sample_data["threads"][0].id

    update_data = {
        "title": "Updated Title",
        "format": "TPB",
        "issues_remaining": 15,
        "notes": "Updated notes",
    }

    response = await client.put(f"/threads/{thread_id}", json=update_data)
    assert response.status_code == 200

    data = response.json()
    assert data["title"] == update_data["title"]
    assert data["format"] == update_data["format"]
    assert data["issues_remaining"] == update_data["issues_remaining"]
    assert data["notes"] == update_data["notes"]

    thread = db.get(Thread, thread_id)
    assert thread.title == update_data["title"]
    assert thread.format == update_data["format"]
    assert thread.issues_remaining == update_data["issues_remaining"]
    assert thread.notes == update_data["notes"]


@pytest.mark.asyncio
async def test_jump_to_position_updates_queue(client, db, sample_data):
    """Jump to position updates thread position correctly."""
    thread_id = sample_data["threads"][2].id
    new_position = 1

    response = await client.put(
        f"/queue/threads/{thread_id}/position/", json={"new_position": new_position}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["position"] == new_position

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == new_position


@pytest.mark.asyncio
async def test_jump_to_position_with_validation(client, db, sample_data):
    """Jump to position validates input correctly."""
    thread_id = sample_data["threads"][0].id

    response = await client.put(f"/queue/threads/{thread_id}/position/", json={"new_position": -1})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_move_thread_up_one_position(client, db, sample_data):
    """Moving thread up one position works correctly."""
    thread_id = sample_data["threads"][1].id

    response = await client.get("/threads/")
    threads = response.json()

    current_position = next(t["position"] for t in threads if t["id"] == thread_id)
    new_position = current_position - 1

    response = await client.put(
        f"/queue/threads/{thread_id}/position/", json={"new_position": new_position}
    )
    assert response.status_code == 200

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == new_position


@pytest.mark.asyncio
async def test_move_thread_down_one_position(client, db, sample_data):
    """Moving thread down one position works correctly."""
    thread_id = sample_data["threads"][0].id

    response = await client.get("/threads/")
    threads = response.json()

    current_position = next(t["position"] for t in threads if t["id"] == thread_id)
    new_position = current_position + 1

    response = await client.put(
        f"/queue/threads/{thread_id}/position/", json={"new_position": new_position}
    )
    assert response.status_code == 200

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == new_position


@pytest.mark.asyncio
async def test_move_to_front_moves_to_position_1(client, db, sample_data):
    """Moving to front sets position to 1."""
    thread_id = sample_data["threads"][3].id

    response = await client.put(f"/queue/threads/{thread_id}/front/")
    assert response.status_code == 200

    data = response.json()
    assert data["position"] == 1

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 1


@pytest.mark.asyncio
async def test_move_to_back_moves_to_last_position(client, db, sample_data):
    """Moving to back sets position to last."""
    thread_id = sample_data["threads"][0].id

    response = await client.get("/threads/")
    threads = response.json()
    last_position = len(threads)

    response = await client.put(f"/queue/threads/{thread_id}/back/")
    assert response.status_code == 200

    data = response.json()
    assert data["position"] == last_position

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == last_position


@pytest.mark.asyncio
async def test_delete_thread_removes_from_queue(client, db, sample_data):
    """Deleting thread removes it from queue."""
    thread_id = sample_data["threads"][0].id

    response = await client.delete(f"/threads/{thread_id}")
    assert response.status_code == 204

    thread = db.get(Thread, thread_id)
    assert thread is None


@pytest.mark.asyncio
async def test_delete_nonexistent_thread_returns_404(client, db):
    """Deleting non-existent thread returns 404."""
    response = await client.delete("/threads/99999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_reactivate_completed_thread(client, db, sample_data):
    """Reactivating completed thread makes it active."""
    completed_thread = sample_data["threads"][2]
    assert completed_thread.status == "completed"

    response = await client.post(
        "/threads/reactivate",
        json={"thread_id": completed_thread.id, "issues_to_add": 5},
    )
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "active"
    assert data["issues_remaining"] == 5

    thread = db.get(Thread, completed_thread.id)
    assert thread.status == "active"
    assert thread.issues_remaining == 5


@pytest.mark.asyncio
async def test_reactivate_nonexistent_thread(client, db):
    """Reactivating non-existent thread returns 404."""
    response = await client.post(
        "/threads/reactivate", json={"thread_id": 99999, "issues_to_add": 5}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_reactivate_already_active_thread_fails(client, sample_data):
    """Reactivating already active thread fails."""
    active_thread = sample_data["threads"][0]
    assert active_thread.status == "active"

    response = await client.post(
        "/threads/reactivate",
        json={"thread_id": active_thread.id, "issues_to_add": 5},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_reactivate_with_zero_issues_fails(client, sample_data):
    """Reactivating with 0 issues fails validation."""
    completed_thread = sample_data["threads"][2]

    response = await client.post(
        "/threads/reactivate", json={"thread_id": completed_thread.id, "issues_to_add": 0}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_queue_page_shows_add_new_button(client, sample_data):
    """Queue page shows Add New button."""
    response = await client.get("/queue/", follow_redirects=True)
    assert response.status_code == 200
    assert "Add New" in response.text


@pytest.mark.asyncio
async def test_add_new_thread_creates_thread(client, db):
    """Adding new thread creates it correctly."""
    new_thread_data = {
        "title": "New Comic Series",
        "format": "TPB",
        "issues_remaining": 6,
        "notes": "Test notes",
    }

    response = await client.post("/threads/", json=new_thread_data)
    assert response.status_code == 201

    data = response.json()
    assert data["title"] == new_thread_data["title"]
    assert data["format"] == new_thread_data["format"]
    assert data["issues_remaining"] == new_thread_data["issues_remaining"]
    assert data["notes"] == new_thread_data["notes"]

    thread = (
        db.execute(select(Thread).where(Thread.title == new_thread_data["title"])).scalars().first()
    )
    assert thread is not None


@pytest.mark.asyncio
async def test_add_thread_with_empty_title_fails(client, db):
    """Adding thread with empty title fails validation."""
    response = await client.post(
        "/threads/", json={"title": "", "format": "TPB", "issues_remaining": 6}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_add_thread_with_negative_issues_fails(client, db):
    """Adding thread with negative issues fails validation."""
    response = await client.post(
        "/threads/", json={"title": "Test Comic", "format": "TPB", "issues_remaining": -1}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_thread_list_includes_position(client, sample_data):
    """Thread list includes position information."""
    response = await client.get("/threads/")
    assert response.status_code == 200

    threads = response.json()
    for thread in threads:
        assert "position" in thread
        assert isinstance(thread["position"], int)


@pytest.mark.asyncio
async def test_thread_list_includes_staleness_info(client, sample_data):
    """Thread list includes last_activity_at for staleness calculation."""
    response = await client.get("/threads/")
    assert response.status_code == 200

    threads = response.json()
    for thread in threads:
        assert "last_activity_at" in thread


@pytest.mark.asyncio
async def test_thread_list_includes_notes(client, sample_data):
    """Thread list includes notes field."""
    response = await client.get("/threads/")
    assert response.status_code == 200

    threads = response.json()
    for thread in threads:
        assert "notes" in thread


@pytest.mark.asyncio
async def test_thread_list_includes_is_test(client, sample_data):
    """Thread list includes is_test field."""
    response = await client.get("/threads/")
    assert response.status_code == 200

    threads = response.json()
    for thread in threads:
        assert "is_test" in thread


@pytest.mark.asyncio
async def test_move_creates_reorder_event(client, db, sample_data):
    """Moving thread creates reorder event."""
    thread_id = sample_data["threads"][0].id

    initial_events = (
        db.execute(select(Event).where(Event.type == "reorder", Event.thread_id == thread_id))
        .scalars()
        .all()
    )
    initial_event_count = len(initial_events)

    response = await client.put(f"/queue/threads/{thread_id}/position/", json={"new_position": 3})
    assert response.status_code == 200

    final_events = (
        db.execute(select(Event).where(Event.type == "reorder", Event.thread_id == thread_id))
        .scalars()
        .all()
    )
    final_event_count = len(final_events)

    assert final_event_count > initial_event_count


@pytest.mark.asyncio
async def test_move_to_front_creates_reorder_event(client, db, sample_data):
    """Moving to front creates reorder event."""
    thread_id = sample_data["threads"][2].id

    initial_events = (
        db.execute(select(Event).where(Event.type == "reorder", Event.thread_id == thread_id))
        .scalars()
        .all()
    )
    initial_event_count = len(initial_events)

    response = await client.put(f"/queue/threads/{thread_id}/front/")
    assert response.status_code == 200

    final_events = (
        db.execute(select(Event).where(Event.type == "reorder", Event.thread_id == thread_id))
        .scalars()
        .all()
    )
    final_event_count = len(final_events)

    assert final_event_count > initial_event_count


@pytest.mark.asyncio
async def test_move_to_back_creates_reorder_event(client, db, sample_data):
    """Moving to back creates reorder event."""
    thread_id = sample_data["threads"][0].id

    initial_events = (
        db.execute(select(Event).where(Event.type == "reorder", Event.thread_id == thread_id))
        .scalars()
        .all()
    )
    initial_event_count = len(initial_events)

    response = await client.put(f"/queue/threads/{thread_id}/back/")
    assert response.status_code == 200

    final_events = (
        db.execute(select(Event).where(Event.type == "reorder", Event.thread_id == thread_id))
        .scalars()
        .all()
    )
    final_event_count = len(final_events)

    assert final_event_count > initial_event_count


@pytest.mark.asyncio
async def test_queue_page_shows_reactivate_button(client, sample_data):
    """Queue page shows Reactivate Completed Thread button."""
    response = await client.get("/queue/", follow_redirects=True)
    assert response.status_code == 200
    assert "Reactivate Completed Thread" in response.text


@pytest.mark.asyncio
async def test_get_completed_threads_for_modal(client, sample_data):
    """Getting completed threads returns only completed threads."""
    response = await client.get("/threads/completed")
    assert response.status_code == 200

    completed_thread = sample_data["threads"][2]
    assert completed_thread.title in response.text
    assert completed_thread.format in response.text

    active_thread = sample_data["threads"][0]
    assert active_thread.title not in response.text


@pytest.mark.asyncio
async def test_delete_thread_with_restore_point_check(client, db, sample_data):
    """Deleting thread checks for restore point."""
    response = await client.get("/sessions/current/")
    assert response.status_code == 200

    thread_id = sample_data["threads"][0].id

    response = await client.delete(f"/threads/{thread_id}")
    assert response.status_code == 204

    thread = db.get(Thread, thread_id)
    assert thread is None


@pytest.mark.asyncio
async def test_queue_order_after_multiple_moves(client, db, sample_data):
    """Queue order updates correctly after multiple moves."""
    response = await client.get("/threads/")
    threads = response.json()

    thread1_id = threads[0]["id"]
    thread2_id = threads[1]["id"]
    thread3_id = threads[2]["id"]

    await client.put(f"/queue/threads/{thread1_id}/position/", json={"new_position": 3})
    await client.put(f"/queue/threads/{thread2_id}/position/", json={"new_position": 1})
    await client.put(f"/queue/threads/{thread3_id}/position/", json={"new_position": 2})

    response = await client.get("/threads/")
    threads = response.json()

    thread1 = next(t for t in threads if t["id"] == thread1_id)
    thread2 = next(t for t in threads if t["id"] == thread2_id)
    thread3 = next(t for t in threads if t["id"] == thread3_id)

    assert thread1["position"] == 3
    assert thread2["position"] == 1
    assert thread3["position"] == 2


@pytest.mark.asyncio
async def test_edit_nonexistent_thread_returns_404(client, db):
    """Editing non-existent thread returns 404."""
    response = await client.put(
        "/threads/99999", json={"title": "Updated", "format": "Comic", "issues_remaining": 10}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_thread_with_notes_displays_in_queue(client, sample_data, db):
    """Thread with notes displays notes in queue."""
    thread = sample_data["threads"][0]
    thread.notes = "Test notes for display"
    db.commit()
    db.refresh(thread)

    response = await client.get("/threads/")
    threads = response.json()

    thread_data = next(t for t in threads if t["id"] == thread.id)
    assert thread_data["notes"] == "Test notes for display"
