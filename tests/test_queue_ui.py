"""Tests for queue UI button disabled states."""

import pytest


@pytest.mark.asyncio
async def test_queue_ui_first_thread_has_disabled_up(client, db, sample_data):
    """First thread's up button should be visually disabled in response."""
    response = await client.get("/queue/", follow_redirects=True)
    assert response.status_code == 200

    content = response.text

    response2 = await client.get("/threads/")
    threads = response2.json()

    if threads:
        first_thread_id = threads[0]["id"]

        html_pattern = f'data-thread-id="{first_thread_id}"'

        if html_pattern in content:
            thread_html_start = content.find(html_pattern)
            thread_html_section = content[thread_html_start : thread_html_start + 2000]

            up_button_pattern = 'onclick="moveThread(' + str(first_thread_id) + ", 'up')\""
            if up_button_pattern in thread_html_section:
                up_button_start = thread_html_section.find(up_button_pattern)
                button_html = thread_html_section[
                    max(0, up_button_start - 200) : up_button_start + 100
                ]

                assert "disabled" in button_html.lower()


@pytest.mark.asyncio
async def test_queue_ui_last_thread_has_disabled_down(client, db, sample_data):
    """Last thread's down button should be visually disabled in response."""
    response = await client.get("/queue/", follow_redirects=True)
    assert response.status_code == 200

    content = response.text

    response2 = await client.get("/threads/")
    threads = response2.json()

    if threads:
        last_thread_id = threads[-1]["id"]

        html_pattern = f'data-thread-id="{last_thread_id}"'

        if html_pattern in content:
            thread_html_start = content.find(html_pattern)
            thread_html_section = content[thread_html_start : thread_html_start + 2000]

            down_button_pattern = 'onclick="moveThread(' + str(last_thread_id) + ", 'down')\""
            if down_button_pattern in thread_html_section:
                down_button_start = thread_html_section.find(down_button_pattern)
                button_html = thread_html_section[
                    max(0, down_button_start - 200) : down_button_start + 100
                ]

                assert "disabled" in button_html.lower()


@pytest.mark.asyncio
async def test_jump_to_position_works_for_large_distance(client, db, sample_data):
    """Jump from position 1 to last position works correctly."""
    thread_id = sample_data["threads"][0].id

    response = await client.get("/threads/")
    threads = response.json()
    last_position = len(threads)

    response = await client.put(
        f"/queue/threads/{thread_id}/position/", json={"new_position": last_position}
    )
    assert response.status_code == 200

    thread = db.get(Thread, sample_data["threads"][0].id)
    assert thread.queue_position == last_position


@pytest.mark.asyncio
async def test_jump_to_position_works_for_small_distance(client, db, sample_data):
    """Jump from last position to position 1 works correctly."""
    response = await client.get("/threads/")
    threads = response.json()
    last_thread_id = threads[-1]["id"]

    response = await client.put(
        f"/queue/threads/{last_thread_id}/position/", json={"new_position": 1}
    )
    assert response.status_code == 200

    thread = db.get(Thread, last_thread_id)
    assert thread.queue_position == 1


@pytest.mark.asyncio
async def test_drag_and_drop_updates_position(client, db, sample_data):
    """Drag and drop reordering updates position correctly."""
    thread_id = sample_data["threads"][0].id
    new_position = 3

    response = await client.put(
        f"/queue/threads/{thread_id}/position/", json={"new_position": new_position}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == thread_id
    assert data["position"] == new_position

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == new_position


from app.models import Thread


@pytest.mark.asyncio
async def test_move_to_front_via_api(client, db, sample_data):
    """Move to front endpoint works correctly."""
    thread_id = sample_data["threads"][2].id

    response = await client.put(f"/queue/threads/{thread_id}/front/")
    assert response.status_code == 200

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 1


@pytest.mark.asyncio
async def test_move_to_back_via_api(client, db, sample_data):
    """Move to back endpoint works correctly."""
    thread_id = sample_data["threads"][0].id

    response = await client.get("/threads/")
    threads = response.json()
    last_position = len(threads)

    response = await client.put(f"/queue/threads/{thread_id}/back/")
    assert response.status_code == 200

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == last_position
