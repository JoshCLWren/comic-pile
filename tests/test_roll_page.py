"""Integration tests for roll.html page interactive elements."""

import re

import pytest

from app.models import Event, Session as SessionModel


@pytest.mark.asyncio
async def test_roll_page_renders(client):
    """GET /roll returns 200 and renders HTML."""
    response = await client.get("/roll")
    assert response.status_code == 200
    assert "<!DOCTYPE html>" in response.text
    assert "Roll" in response.text


@pytest.mark.asyncio
async def test_roll_page_contains_dice_grid(client):
    """Roll page contains dice grid element."""
    response = await client.get("/roll", follow_redirects=True)
    assert response.status_code == 200
    html = response.text
    assert 'id="dice-grid"' in html


@pytest.mark.asyncio
async def test_roll_page_contains_roll_container(client):
    """Roll page contains roll container for HTMX."""
    response = await client.get("/roll", follow_redirects=True)
    assert response.status_code == 200
    html = response.text
    assert 'id="roll-container"' in html
    assert 'id="result"' in html


@pytest.mark.asyncio
async def test_roll_page_contains_tap_instruction(client):
    """Roll page contains tap instruction text."""
    response = await client.get("/roll", follow_redirects=True)
    assert response.status_code == 200
    html = response.text
    assert 'id="tap-instruction"' in html
    assert "Tap Anywhere to Roll" in html


@pytest.mark.asyncio
async def test_roll_page_contains_die_selector_buttons(client):
    """Roll page contains die selector buttons."""
    response = await client.get("/roll", follow_redirects=True)
    assert response.status_code == 200
    html = response.text
    assert 'id="die-selector"' in html
    for die in [4, 6, 8, 10, 12, 20]:
        assert f'href="/roll/set-die?die={die}"' in html or f'data-die="{die}"' in html


@pytest.mark.asyncio
async def test_roll_page_contains_auto_mode_button(client):
    """Roll page contains auto mode button."""
    response = await client.get("/roll", follow_redirects=True)
    assert response.status_code == 200
    html = response.text
    assert 'id="auto-mode-btn"' in html
    assert 'hx-post="/roll/clear-manual-die"' in html


@pytest.mark.asyncio
async def test_roll_page_contains_current_die_label(client):
    """Roll page contains current die display in header."""
    response = await client.get("/roll", follow_redirects=True)
    assert response.status_code == 200
    html = response.text
    assert (
        "d{{ current_die }}" in html
        or 'class="text-[9px] font-black text-slate-500 uppercase">d' in html
    )


@pytest.mark.asyncio
async def test_roll_page_contains_session_safe_indicator(client):
    """Roll page contains session safe indicator element."""
    response = await client.get("/roll")
    assert response.status_code == 200
    html = response.text
    assert 'id="session-safe-indicator"' in html


@pytest.mark.asyncio
async def test_roll_page_contains_stale_suggestion(client):
    """Roll page contains stale suggestion element."""
    response = await client.get("/roll")
    assert response.status_code == 200
    html = response.text
    assert 'id="stale-suggestion"' in html
    assert 'id="stale-text"' in html


@pytest.mark.asyncio
async def test_roll_page_contains_explosion_layer(client):
    """Roll page contains explosion layer for visual effects."""
    response = await client.get("/roll")
    assert response.status_code == 200
    html = response.text
    assert 'id="explosion-layer"' in html
    assert 'class="explosion-wrap"' in html


@pytest.mark.asyncio
async def test_roll_page_javascript_dice_ladder_constant(client):
    """Roll page JavaScript contains DICE_LADDER constant."""
    response = await client.get("/roll")
    assert response.status_code == 200
    html = response.text
    assert "DICE_LADDER" in html
    assert "[4, 6, 8, 10, 12, 20]" in html


@pytest.mark.asyncio
async def test_roll_page_javascript_initdice_function(client):
    """Roll page JavaScript contains initDice function."""
    response = await client.get("/roll")
    assert response.status_code == 200
    html = response.text
    assert "function initDice()" in html


@pytest.mark.asyncio
async def test_roll_page_javascript_rollthedie_function(client):
    """Roll page JavaScript contains rollTheDie function."""
    response = await client.get("/roll")
    assert response.status_code == 200
    html = response.text
    assert "function rollTheDie()" in html


@pytest.mark.asyncio
async def test_roll_page_javascript_loadrollpool_function(client):
    """Roll page JavaScript contains loadRollPool function."""
    response = await client.get("/roll")
    assert response.status_code == 200
    html = response.text
    assert "async function loadRollPool()" in html


@pytest.mark.asyncio
async def test_roll_page_javascript_submitrating_function(client):
    """Roll page JavaScript contains submitRating function."""
    response = await client.get("/roll")
    assert response.status_code == 200
    html = response.text
    assert "async function submitRating()" in html


@pytest.mark.asyncio
async def test_roll_page_javascript_triggerreroll_function(client):
    """Roll page JavaScript contains triggerReroll function."""
    response = await client.get("/roll")
    assert response.status_code == 200
    html = response.text
    assert "async function triggerReroll()" in html


@pytest.mark.asyncio
async def test_roll_page_javascript_checkmanualmode_function(client):
    """Roll page JavaScript contains checkManualMode function."""
    response = await client.get("/roll")
    assert response.status_code == 200
    html = response.text
    assert "async function checkManualMode()" in html


@pytest.mark.asyncio
async def test_roll_page_javascript_checkrestorepoint_function(client):
    """Roll page JavaScript contains checkRestorePointBeforeSubmit function."""
    response = await client.get("/roll")
    assert response.status_code == 200
    html = response.text
    assert "async function checkRestorePointBeforeSubmit()" in html


@pytest.mark.asyncio
async def test_roll_page_javascript_loadstalesuggestion_function(client):
    """Roll page JavaScript contains loadStaleSuggestion function."""
    response = await client.get("/roll")
    assert response.status_code == 200
    html = response.text
    assert "async function loadStaleSuggestion()" in html


@pytest.mark.asyncio
async def test_roll_page_javascript_updateratingdisplay_function(client):
    """Roll page JavaScript contains updateRatingDisplay function."""
    response = await client.get("/roll")
    assert response.status_code == 200
    html = response.text
    assert "function updateRatingDisplay(val)" in html


@pytest.mark.asyncio
async def test_roll_page_javascript_updatediebuttonstate_function(client):
    """Roll page JavaScript contains updateDieButtonState function."""
    response = await client.get("/roll")
    assert response.status_code == 200
    html = response.text
    assert "function updateDieButtonState(die)" in html


@pytest.mark.asyncio
async def test_roll_page_javascript_createexplosion_function(client):
    """Roll page JavaScript contains createExplosion function."""
    response = await client.get("/roll")
    assert response.status_code == 200
    html = response.text
    assert "function createExplosion()" in html


@pytest.mark.asyncio
async def test_roll_html_endpoint_returns_dice_grid(client, sample_data):
    """POST /roll/html returns dice grid with thread previews."""
    response = await client.post("/roll/html")
    assert response.status_code == 200
    html = response.text
    assert "dice-grid" in html
    assert "dice-container" in html
    assert "thread-preview" in html


@pytest.mark.asyncio
async def test_roll_html_endpoint_contains_data_result(client, sample_data):
    """POST /roll/html returns data-result attribute."""
    response = await client.post("/roll/html")
    assert response.status_code == 200
    html = response.text
    assert 'data-result="' in html


@pytest.mark.asyncio
async def test_roll_html_endpoint_contains_rating_form(client, sample_data):
    """POST /roll/html returns rating form container."""
    response = await client.post("/roll/html")
    assert response.status_code == 200
    html = response.text
    assert "rating-form-container" in html
    assert 'id="rating-input"' in html
    assert 'id="submit-rating-btn"' in html


@pytest.mark.asyncio
async def test_roll_html_endpoint_contains_reroll_button(client, sample_data):
    """POST /roll/html returns reroll button."""
    response = await client.post("/roll/html")
    assert response.status_code == 200
    html = response.text
    assert 'id="reroll-btn"' in html
    assert "Reroll Dice" in html


@pytest.mark.asyncio
async def test_roll_html_endpoint_contains_error_message(client, sample_data):
    """POST /roll/html returns error message element."""
    response = await client.post("/roll/html")
    assert response.status_code == 200
    html = response.text
    assert 'id="error-message"' in html


@pytest.mark.asyncio
async def test_roll_html_endpoint_returns_valid_thread(client, sample_data, db):
    """POST /roll/html returns HTML with valid thread from pool."""
    response = await client.post("/roll/html")
    assert response.status_code == 200
    html = response.text

    match = re.search(r'<div class="thread-preview-title">(.+?)</div>', html)
    assert match is not None, "HTML should contain thread preview title"
    thread_title = match.group(1)

    assert thread_title != "Empty", "Thread should not be empty when threads exist"

    thread_titles = [t.title for t in sample_data["threads"] if t.status == "active"]
    assert thread_title in thread_titles, (
        f"Thread title '{thread_title}' should be in active threads"
    )


@pytest.mark.asyncio
async def test_roll_html_endpoint_updates_pending_thread(client, sample_data):
    """POST /roll/html updates pending_thread_id."""
    response = await client.post("/roll/html")
    assert response.status_code == 200
    html = response.text
    assert "localStorage.setItem('selectedThreadId'" in html


@pytest.mark.asyncio
async def test_roll_html_endpoint_creates_event(client, sample_data, db):
    """POST /roll/html creates roll event."""
    from sqlalchemy import select

    initial_events = (
        db.execute(
            select(Event).where(Event.type == "roll").where(Event.selection_method == "random")
        )
        .scalars()
        .all()
    )
    initial_count = len(initial_events)

    await client.post("/roll/html")

    new_events = (
        db.execute(
            select(Event).where(Event.type == "roll").where(Event.selection_method == "random")
        )
        .scalars()
        .all()
    )
    assert len(new_events) == initial_count + 1


@pytest.mark.asyncio
async def test_roll_html_endpoint_no_pool_returns_message(client, db):
    """POST /roll/html returns message when no active threads."""
    from tests.conftest import get_or_create_user

    get_or_create_user(db)

    response = await client.post("/roll/html")
    assert response.status_code == 200
    assert "No active threads" in response.text


@pytest.mark.asyncio
async def test_roll_page_contains_pending_alert(client, sample_data, db):
    """GET /roll contains pending thread alert when pending_thread_id exists."""
    from sqlalchemy import select
    from datetime import datetime, timedelta

    session = (
        db.execute(select(SessionModel).where(SessionModel.ended_at.is_(None))).scalars().first()
    )
    assert session is not None

    thread = sample_data["threads"][0]
    session.pending_thread_id = thread.id
    session.pending_thread_updated_at = datetime.now() - timedelta(hours=1)
    db.commit()

    response = await client.get("/roll")
    assert response.status_code == 200
    html = response.text
    assert "pending-thread-alert" in html or thread.title not in html


@pytest.mark.asyncio
async def test_reroll_endpoint_returns_dice_grid(client, sample_data):
    """POST /roll/reroll returns dice grid with updated selection."""
    response = await client.post("/roll/reroll")
    assert response.status_code == 200
    html = response.text
    assert "dice-grid" in html
    assert "rating-form-container" in html


@pytest.mark.asyncio
async def test_reroll_endpoint_creates_reroll_event(client, sample_data, db):
    """POST /roll/reroll creates event with selection_method='reroll'."""
    from sqlalchemy import select

    response = await client.post("/roll/reroll")
    assert response.status_code == 200

    new_events = (
        db.execute(
            select(Event).where(Event.type == "roll").where(Event.selection_method == "reroll")
        )
        .scalars()
        .all()
    )
    assert len(new_events) >= 1


@pytest.mark.asyncio
async def test_set_die_endpoint_sets_manual_die(client, sample_data):
    """POST /roll/set-die returns correct response."""
    from app.main import _session_cache, clear_cache

    _session_cache.clear()
    clear_cache()

    response = await client.post("/roll/set-die?die=20")
    assert response.status_code == 200
    assert response.text == "d20"


@pytest.mark.asyncio
async def test_set_die_endpoint_invalid_die_returns_error(client, sample_data):
    """POST /roll/set-die with invalid die returns 400."""
    response = await client.post("/roll/set-die?die=99")
    assert response.status_code == 400
    assert "Invalid die size" in response.text


@pytest.mark.asyncio
async def test_set_die_endpoint_all_valid_dice(client, sample_data):
    """POST /roll/set-die works for all valid die sizes."""
    for die in [4, 6, 8, 10, 12, 20]:
        response = await client.post(f"/roll/set-die?die={die}")
        assert response.status_code == 200
        assert response.text == f"d{die}"


@pytest.mark.asyncio
async def test_clear_manual_die_endpoint_clears_manual_mode(client, sample_data, db):
    """POST /roll/clear-manual-die returns HTML response."""
    response = await client.post("/roll/clear-manual-die")
    assert response.status_code == 200
    assert response.text.startswith("d")


@pytest.mark.asyncio
async def test_clear_manual_die_endpoint_returns_current_die(client, sample_data, db):
    """POST /roll/clear-manual-die returns correct current die."""
    from sqlalchemy import select

    session = (
        db.execute(select(SessionModel).where(SessionModel.ended_at.is_(None))).scalars().first()
    )
    assert session is not None

    response = await client.post("/roll/clear-manual-die")
    assert response.status_code == 200

    session_response = await client.get("/sessions/current/")
    assert session_response.status_code == 200
    session_data = session_response.json()

    expected_die = session_data["current_die"]
    assert response.text == f"d{expected_die}"


@pytest.mark.asyncio
async def test_dismiss_pending_endpoint_clears_pending_thread(client, sample_data):
    """POST /roll/dismiss-pending returns empty response."""
    response = await client.post("/roll/dismiss-pending")
    assert response.status_code == 200
    assert response.text == ""


@pytest.mark.asyncio
async def test_roll_page_with_pending_thread_shows_alert(client, sample_data, db):
    """Roll page handles pending thread state."""
    from sqlalchemy import select
    from datetime import datetime, timedelta

    session = (
        db.execute(select(SessionModel).where(SessionModel.ended_at.is_(None))).scalars().first()
    )
    assert session is not None

    thread = sample_data["threads"][0]
    session.pending_thread_id = thread.id
    session.pending_thread_updated_at = datetime.now() - timedelta(hours=1)
    db.commit()

    response = await client.get("/roll")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_roll_page_without_pending_thread_no_alert(client, sample_data):
    """Roll page does not show pending thread alert when no pending thread."""
    response = await client.get("/roll")
    assert response.status_code == 200
    html = response.text
    assert "You were about to read:" not in html


@pytest.mark.asyncio
async def test_roll_html_endpoint_respects_current_die(client, sample_data, db):
    """POST /roll/html respects current die size for pool size."""
    from sqlalchemy import select

    session = (
        db.execute(select(SessionModel).where(SessionModel.ended_at.is_(None))).scalars().first()
    )
    assert session is not None

    session.manual_die = 4
    db.commit()

    response = await client.post("/roll/html")
    assert response.status_code == 200
    html = response.text

    die_pattern = re.compile(r"rolledResult = (\d+);")
    match = die_pattern.search(html)
    assert match is not None
    result = int(match.group(1))
    assert 1 <= result <= 4


@pytest.mark.asyncio
async def test_roll_endpoint_returns_thread_info(client, sample_data):
    """POST /roll/ returns JSON with thread info."""
    response = await client.post("/roll/")
    assert response.status_code == 200

    data = response.json()
    assert "thread_id" in data
    assert "title" in data
    assert "die_size" in data
    assert "result" in data


@pytest.mark.asyncio
async def test_roll_endpoint_returns_valid_result(client, sample_data):
    """POST /roll/ returns result within valid range."""
    response = await client.post("/roll/")
    assert response.status_code == 200

    data = response.json()
    die_size = data["die_size"]
    result = data["result"]
    assert 1 <= result <= die_size


@pytest.mark.asyncio
async def test_override_endpoint_returns_specified_thread(client, sample_data):
    """POST /roll/override returns specified thread."""
    thread = sample_data["threads"][0]
    response = await client.post("/roll/override", json={"thread_id": thread.id})
    assert response.status_code == 200

    data = response.json()
    assert data["thread_id"] == thread.id
    assert data["title"] == thread.title
    assert data["result"] == 0


@pytest.mark.asyncio
async def test_override_endpoint_nonexistent_thread_returns_404(client):
    """POST /roll/override with non-existent thread returns 404."""
    response = await client.post("/roll/override", json={"thread_id": 999})
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_roll_page_javascript_updates_on_htmx_request(client, sample_data):
    """Roll page JavaScript handles HTMX afterRequest events."""
    response = await client.get("/roll")
    assert response.status_code == 200
    html = response.text
    assert "htmx:afterRequest" in html


@pytest.mark.asyncio
async def test_roll_page_dice_container_classes(client, sample_data):
    """Roll page dice containers have correct CSS classes."""
    response = await client.post("/roll/html")
    assert response.status_code == 200
    html = response.text
    assert 'class="dice-container' in html
    assert "selected" in html or "ladder-active" in html


@pytest.mark.asyncio
async def test_roll_page_thread_preview_classes(client, sample_data):
    """Roll page thread previews have correct CSS classes."""
    response = await client.post("/roll/html")
    assert response.status_code == 200
    html = response.text
    assert 'class="thread-preview' in html


@pytest.mark.asyncio
async def test_roll_page_rating_input_attributes(client, sample_data):
    """Roll page rating input has correct attributes."""
    response = await client.post("/roll/html")
    assert response.status_code == 200
    html = response.text
    assert 'type="range"' in html
    assert 'min="0.5"' in html
    assert 'max="5.0"' in html
    assert 'step="0.5"' in html
    assert 'value="4.0"' in html


@pytest.mark.asyncio
async def test_roll_page_rating_value_display(client, sample_data):
    """Roll page contains rating value display element."""
    response = await client.post("/roll/html")
    assert response.status_code == 200
    html = response.text
    assert 'id="rating-value"' in html
    assert 'id="rating-preview"' in html


@pytest.mark.asyncio
async def test_reroll_endpoint_no_pool_returns_message(client, db):
    """POST /roll/reroll returns message when no active threads."""
    from tests.conftest import get_or_create_user

    get_or_create_user(db)

    response = await client.post("/roll/reroll")
    assert response.status_code == 200
    assert "No active threads" in response.text


@pytest.mark.asyncio
async def test_roll_page_javascript_localstorage_handling(client):
    """Roll page JavaScript handles localStorage for selectedThreadId."""
    response = await client.get("/roll", follow_redirects=True)
    assert response.status_code == 200
    html = response.text
    assert "localStorage.getItem('selectedThreadId')" in html
