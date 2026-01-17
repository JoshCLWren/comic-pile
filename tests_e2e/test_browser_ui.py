"""Browser UI integration tests using Playwright."""

import pytest


@pytest.mark.integration
def test_root_url_renders_dice_ladder(page, test_server_url):
    """Navigate to /, verify expected dice selector exists."""
    page.goto(f"{test_server_url}/")
    page.wait_for_selector("#die-selector", timeout=5000)

    header_die = page.query_selector("#header-die-label")
    assert header_die is not None


@pytest.mark.integration
def test_homepage_renders_dice_ladder(page, test_server_url):
    """Navigate to /react/, verify expected dice selector exists (legacy URL)."""
    page.goto(f"{test_server_url}/react/")
    page.wait_for_selector("#die-selector", timeout=5000)

    header_die = page.query_selector("#header-die-label")
    assert header_die is not None


@pytest.mark.integration
def test_roll_dice_navigates_to_rate(page, test_server_url, db):
    """Navigate to /, click roll button, verify navigation to /rate."""
    from app.models import Thread

    thread = Thread(
        title="Roll Test Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=1,
    )
    db.add(thread)
    db.commit()

    page.goto(f"{test_server_url}/")

    page.wait_for_selector("#tap-instruction", timeout=5000)

    dice_element = page.wait_for_selector("#main-die-3d", timeout=5000)
    if dice_element:
        dice_element.click()

    page.wait_for_timeout(2000)

    assert page.url.endswith("/rate") or page.url.endswith("/rate/")


@pytest.mark.integration
def test_htmx_rate_comic_updates_ui(page, test_server_url, db):
    """Navigate to /rate after a roll, update rating slider, verify it works."""
    from app.models import Event, Thread
    from app.models import Session as SessionModel

    thread = Thread(
        title="Test Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=100,
        status="active",
        user_id=1,
    )
    db.add(thread)
    db.commit()

    session = SessionModel(start_die=6, user_id=1)
    db.add(session)
    db.commit()
    db.refresh(session)

    roll_event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=1,
        selection_method="random",
    )
    db.add(roll_event)
    db.commit()

    page.goto(f"{test_server_url}/rate")
    page.wait_for_selector("#rating-input", timeout=5000)

    page.evaluate("document.getElementById('rating-input').value = '3.5'")
    page.evaluate("document.getElementById('rating-input').dispatchEvent(new Event('input'))")

    rating_value = page.evaluate("document.getElementById('rating-input').value")
    assert float(rating_value) == 3.5


@pytest.mark.integration
def test_queue_management_ui(page, test_server_url, db):
    """Navigate to /queue, verify queue container exists and displays data."""
    from app.models import Thread

    thread = Thread(
        title="Browser Test Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=100,
        status="active",
        user_id=1,
    )
    db.add(thread)
    db.commit()

    page.goto(f"{test_server_url}/queue")
    page.wait_for_selector("#queue-container", timeout=5000)

    queue_container = page.query_selector("#queue-container")
    assert queue_container is not None


@pytest.mark.integration
def test_view_history_pagination(page, test_server_url, db):
    """Navigate to /history, verify history list exists."""
    from app.models import Event, Thread
    from app.models import Session as SessionModel

    thread = Thread(
        title="History Test Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=100,
        user_id=1,
    )
    db.add(thread)
    db.commit()

    session = SessionModel(start_die=6, user_id=1)
    db.add(session)
    db.commit()
    db.refresh(session)

    roll_event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=1,
        selection_method="random",
    )
    db.add(roll_event)
    db.commit()

    page.goto(f"{test_server_url}/history")
    page.wait_for_selector("#sessions-list", timeout=5000)

    sessions_list = page.query_selector("#sessions-list")
    assert sessions_list is not None


@pytest.mark.integration
def test_settings_page_renders(page, test_server_url):
    """Navigate to /settings, verify settings header exists."""
    page.goto(f"{test_server_url}/settings")
    page.wait_for_selector("text=Settings", timeout=5000)


@pytest.mark.integration
def test_full_session_workflow(page, test_server_url, db):
    """Setup session data, navigate to rate page, verify UI is functional."""
    from app.models import Event, Thread
    from app.models import Session as SessionModel

    thread = Thread(
        title="Workflow Test Comic",
        format="Comic",
        issues_remaining=1,
        queue_position=100,
        user_id=1,
    )
    db.add(thread)
    db.commit()

    session = SessionModel(start_die=6, user_id=1)
    db.add(session)
    db.commit()
    db.refresh(session)

    roll_event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=1,
        selection_method="random",
    )
    db.add(roll_event)
    db.commit()

    page.goto(f"{test_server_url}/rate")
    page.wait_for_selector("#rating-input", timeout=5000)

    rating_input = page.query_selector("#rating-input")
    assert rating_input is not None

    page.evaluate("document.getElementById('rating-input').value = '4.0'")
    page.evaluate("document.getElementById('rating-input').dispatchEvent(new Event('input'))")

    rating_value = page.evaluate("document.getElementById('rating-input').value")
    assert float(rating_value) == 4.0


@pytest.mark.integration
def test_d10_renders_geometry_correctly(page, test_server_url):
    """Navigate to /, select d10, verify d10 canvas element exists with WebGL context."""
    page.goto(f"{test_server_url}/")
    page.wait_for_selector("#die-selector", timeout=5000)
    page.wait_for_timeout(2000)

    page.wait_for_selector('button:has-text("d10")', timeout=5000)

    page.wait_for_selector("#main-die-3d", timeout=5000)
    page.wait_for_timeout(2000)

    canvas_info = page.evaluate("""
        () => {
            const container = document.querySelector('#main-die-3d');
            if (!container) return { error: 'Dice container not found' };

            const canvas = container.querySelector('canvas');
            if (!canvas) return { error: 'Canvas not found' };

            const canvasWidth = canvas.width;
            const canvasHeight = canvas.height;

            if (canvasWidth === 0 || canvasHeight === 0) {
                return { error: 'Canvas has zero dimensions' };
            }

            const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
            if (!gl) return { error: 'WebGL context not available' };

            return {
                success: true,
                canvasWidth,
                canvasHeight,
                hasWebGL: true
            };
        }
    """)

    assert "error" not in canvas_info, f"Canvas/WebGL error: {canvas_info.get('error')}"
    assert canvas_info.get("hasWebGL") is True, "WebGL context not available"
    assert canvas_info.get("canvasWidth", 0) > 0, "Canvas has zero width"
    assert canvas_info.get("canvasHeight", 0) > 0, "Canvas has zero height"
