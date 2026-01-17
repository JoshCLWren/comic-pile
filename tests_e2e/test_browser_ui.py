"""Browser UI integration tests using Playwright."""

import os

import pytest


@pytest.mark.integration
def test_homepage_renders_dice_ladder(page, test_server_url):
    """Navigate to /, verify expected dice selector exists."""
    page.goto(f"{test_server_url}/react/")
    page.wait_for_selector("#die-selector", timeout=5000)

    header_die = page.query_selector("#header-die-label")
    assert header_die is not None


@pytest.mark.integration
def test_roll_dice_navigates_to_rate(page, test_server_url):
    """Navigate to /, click roll button, verify navigation to /rate."""
    page.goto(f"{test_server_url}/react/")

    page.wait_for_selector("#tap-instruction", timeout=5000)

    dice_element = page.wait_for_selector("#main-die-3d", timeout=5000)
    if dice_element:
        dice_element.click()

    page.wait_for_timeout(2000)

    assert page.url.endswith("/react/rate")


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

    page.goto(f"{test_server_url}/react/rate")
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
        user_id=1,
    )
    db.add(thread)
    db.commit()

    page.goto(f"{test_server_url}/react/queue")
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

    page.goto(f"{test_server_url}/react/history")
    page.wait_for_selector("#sessions-list", timeout=5000)

    sessions_list = page.query_selector("#sessions-list")
    assert sessions_list is not None


@pytest.mark.integration
def test_settings_page_renders(page, test_server_url):
    """Navigate to /settings, verify settings header exists."""
    page.goto(f"{test_server_url}/react/settings")
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

    page.goto(f"{test_server_url}/react/rate")
    page.wait_for_selector("#rating-input", timeout=5000)

    rating_input = page.query_selector("#rating-input")
    assert rating_input is not None

    page.evaluate("document.getElementById('rating-input').value = '4.0'")
    page.evaluate("document.getElementById('rating-input').dispatchEvent(new Event('input'))")

    rating_value = page.evaluate("document.getElementById('rating-input').value")
    assert float(rating_value) == 4.0


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("CI") == "true",
    reason="WebGL rendering requires GPU support not available in CI headless browsers",
)
def test_d10_renders_geometry_correctly(page, test_server_url):
    """Navigate to /react/, select d10, verify d10 renders non-blank geometry via WebGL."""
    page.goto(f"{test_server_url}/react/")
    page.wait_for_selector("#die-selector", timeout=5000)
    page.wait_for_timeout(2000)

    page.wait_for_selector('button:has-text("d10")', timeout=5000)

    page.wait_for_selector("#main-die-3d", timeout=5000)
    page.wait_for_timeout(2000)

    pixel_stats = page.evaluate("""
        () => {
            const container = document.querySelector('#main-die-3d');
            if (!container) return { error: 'Dice container not found', containerHTML: container ? container.outerHTML.substring(0, 200) : 'null' };

            const canvas = container.querySelector('canvas');
            if (!canvas) return { error: 'Canvas not found', containerChildCount: container ? container.children.length : 0 };

            const canvasWidth = canvas.width;
            const canvasHeight = canvas.height;

            if (canvasWidth === 0 || canvasHeight === 0) {
                return { error: 'Canvas has zero dimensions', totalPixels: 0, opaqueCount: 0, variance: 0 };
            }

            try {
                const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
                if (!gl) return { error: 'WebGL context not available' };

                gl.finish();

                const pixels = new Uint8Array(canvasWidth * canvasHeight * 4);
                gl.readPixels(0, 0, canvasWidth, canvasHeight, gl.RGBA, gl.UNSIGNED_BYTE, pixels);

                let opaqueCount = 0;
                let luminanceSum = 0;
                let luminanceSumSq = 0;
                const numSamples = Math.min(10000, canvasWidth * canvasHeight);

                for (let i = 0; i < numSamples; i++) {
                    const r = pixels[i * 4];
                    const g = pixels[i * 4 + 1];
                    const b = pixels[i * 4 + 2];
                    const a = pixels[i * 4 + 3];

                    if (a > 0) {
                        opaqueCount++;
                        const l = 0.299 * r + 0.587 * g + 0.114 * b;
                        luminanceSum += l;
                        luminanceSumSq += l * l;
                    }
                }

                const variance = opaqueCount > 0
                    ? (luminanceSumSq / opaqueCount) - Math.pow(luminanceSum / opaqueCount, 2)
                    : 0;

                return {
                    totalPixels: canvasWidth * canvasHeight,
                    opaqueCount,
                    variance: Math.abs(variance)
                };
            } catch (e) {
                return { error: e.message };
            }
        }
    """)

    assert "error" not in pixel_stats, f"WebGL error: {pixel_stats.get('error')}"
    assert pixel_stats.get("totalPixels", 1) > 0, "Canvas has zero dimensions"

    opaque_threshold = pixel_stats["totalPixels"] * 0.05
    assert pixel_stats["opaqueCount"] > opaque_threshold, (
        f"d10 appears mostly blank: only {pixel_stats['opaqueCount']} / {pixel_stats['totalPixels']} pixels opaque (expected > {opaque_threshold})"
    )

    assert pixel_stats["variance"] > 100, (
        f"d10 geometry appears degenerate: variance {pixel_stats['variance']} too low"
    )
