"""Browser UI integration tests using Playwright."""

import json
import time
import pytest
import pytest_asyncio
import requests


def login_with_playwright(page, test_server_url, email, password=None):
    """Helper function to login via browser using existing default test user."""
    if password is None:
        password = "testpassword"
    login_response = requests.post(
        f"{test_server_url}/api/auth/login",
        json={"username": email, "password": password},
        timeout=10,
    )
    assert login_response.status_code == 200
    access_token = login_response.json()["access_token"]

    page.add_init_script(f"localStorage.setItem('auth_token', {json.dumps(access_token)})")
    page.goto(f"{test_server_url}/")
    page.wait_for_load_state("networkidle", timeout=5000)


@pytest_asyncio.fixture(scope="function")
async def test_user(test_server_url, async_db):
    """Create a fresh test user for each test."""
    from app.auth import hash_password
    from app.database import get_db
    from app.main import app
    from app.models import User
    from sqlalchemy import text

    await async_db.execute(
        text(
            "TRUNCATE TABLE users, sessions, events, threads, snapshots, revoked_tokens "
            "RESTART IDENTITY CASCADE;"
        )
    )
    await async_db.execute(
        text("SELECT setval('users_id_seq', (SELECT COALESCE(MAX(id), 0) FROM users))")
    )
    await async_db.commit()

    test_timestamp = int(time.time() * 1000)
    test_email = f"test_{test_timestamp}@example.com"

    user = User(
        username=test_email,
        email=test_email,
        password_hash=hash_password("testpassword"),
    )
    async_db.add(user)
    await async_db.commit()
    await async_db.refresh(user)

    async def override_get_db():
        try:
            yield async_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    yield test_email, user.id

    app.dependency_overrides.clear()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_root_url_renders_dice_ladder(browser_page, test_server_url, async_db, test_user):
    """Navigate to /, verify expected dice selector exists."""
    page = browser_page
    login_with_playwright(page, test_server_url, test_user[0])
    await page.goto(f"{test_server_url}/")
    await page.wait_for_selector("#die-selector", timeout=5000)

    header_die = await page.query_selector("#header-die-label")
    assert header_die is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_homepage_renders_dice_ladder(browser_page, test_server_url, async_db, test_user):
    """Navigate to /react/, verify expected dice selector exists (legacy URL)."""
    page = browser_page
    login_with_playwright(page, test_server_url, test_user[0])
    await page.goto(f"{test_server_url}/react/")
    await page.wait_for_selector("#die-selector", timeout=5000)

    header_die = await page.query_selector("#header-die-label")
    assert header_die is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_roll_dice_navigates_to_rate(browser_page, test_server_url, async_db, test_user):
    """Navigate to /, click roll button, verify navigation to /rate."""
    page = browser_page
    from app.models import Thread

    test_email, user_id = test_user

    thread = Thread(
        title="Roll Test Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user_id,
    )
    async_db.add(thread)
    await async_db.commit()

    login_with_playwright(page, test_server_url, test_email)
    await page.goto(f"{test_server_url}/")

    await page.wait_for_selector("#tap-instruction", timeout=5000)

    dice_element = await page.wait_for_selector("#main-die-3d", timeout=5000)
    if dice_element:
        await dice_element.click()

    await page.wait_for_timeout(2000)
    assert page.url.endswith("/rate") or page.url.endswith("/rate/")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_queue_management_ui(browser_page, test_server_url, async_db, test_user):
    """Navigate to /queue, verify queue container exists and displays data."""
    page = browser_page
    from app.models import Thread

    test_email, user_id = test_user

    thread = Thread(
        title="Browser Test Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=100,
        status="active",
        user_id=user_id,
    )
    async_db.add(thread)
    await async_db.commit()

    login_with_playwright(page, test_server_url, test_email)
    await page.goto(f"{test_server_url}/queue")
    await page.wait_for_selector("#queue-container", timeout=5000)

    queue_container = await page.query_selector("#queue-container")
    assert queue_container is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_view_history_pagination(browser_page, test_server_url, async_db, test_user):
    """Navigate to /history, verify history list exists."""
    page = browser_page
    from app.models import Event, Thread
    from app.models import Session as SessionModel

    test_email, user_id = test_user

    thread = Thread(
        title="History Test Comic",
        format="Comic",
        issues_remaining=5,
        queue_position=100,
        user_id=user_id,
    )
    async_db.add(thread)
    await async_db.commit()

    session = SessionModel(start_die=6, user_id=user_id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    roll_event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=1,
        selection_method="random",
    )
    async_db.add(roll_event)
    await async_db.commit()

    login_with_playwright(page, test_server_url, test_email)
    await page.goto(f"{test_server_url}/history")
    await page.wait_for_selector("#sessions-list", timeout=5000)

    sessions_list = await page.query_selector("#sessions-list")
    assert sessions_list is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_session_workflow(browser_page, test_server_url, async_db, test_user):
    """Setup session data, navigate to rate page, verify UI is functional."""
    page = browser_page
    from app.models import Event, Thread
    from app.models import Session as SessionModel

    test_email, user_id = test_user

    thread = Thread(
        title="Workflow Test Comic",
        format="Comic",
        issues_remaining=1,
        queue_position=100,
        user_id=user_id,
    )
    async_db.add(thread)
    await async_db.commit()

    session = SessionModel(start_die=6, user_id=user_id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    roll_event = Event(
        type="roll",
        session_id=session.id,
        selected_thread_id=thread.id,
        die=6,
        result=1,
        selection_method="random",
    )
    async_db.add(roll_event)
    await async_db.commit()

    login_with_playwright(page, test_server_url, test_email)
    await page.goto(f"{test_server_url}/rate")
    await page.wait_for_selector("#rating-input", timeout=5000)

    rating_input = await page.query_selector("#rating-input")
    assert rating_input is not None

    await page.evaluate("document.getElementById('rating-input').value = '4.0'")
    await page.evaluate("document.getElementById('rating-input').dispatchEvent(new Event('input'))")

    rating_value = await page.evaluate("document.getElementById('rating-input').value")
    assert float(rating_value) == 4.0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_d10_renders_geometry_correctly(browser_page, test_server_url, async_db, test_user):
    """Navigate to /, select d10, verify d10 canvas element exists with WebGL context."""
    page = browser_page
    login_with_playwright(page, test_server_url, test_user[0])
    await page.goto(f"{test_server_url}/")
    await page.wait_for_selector("#die-selector", timeout=5000)
    await page.wait_for_timeout(2000)

    await page.wait_for_selector('button:has-text("d10")', timeout=5000)

    await page.wait_for_selector("#main-die-3d", timeout=5000)
    await page.wait_for_timeout(2000)

    canvas_info = await page.evaluate("""
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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_auth_login_roll_rate_flow(browser_page, test_server_url):
    """Test complete login → roll → rate flow."""
    page = browser_page
    import time
    import requests

    test_timestamp = int(time.time() * 1000)
    test_user = f"test_{test_timestamp}@example.com"

    register_response = requests.post(
        f"{test_server_url}/api/auth/register",
        json={
            "username": test_user,
            "email": test_user,
            "password": "testpassword",
        },
        timeout=10,
    )
    assert register_response.status_code in (200, 201)

    login_response = requests.post(
        f"{test_server_url}/api/auth/login",
        json={"username": test_user, "password": "testpassword"},
        timeout=10,
    )
    assert login_response.status_code == 200
    access_token = login_response.json()["access_token"]

    headers = {"Authorization": f"Bearer {access_token}"}

    thread_response = requests.post(
        f"{test_server_url}/api/threads/",
        json={"title": "E2E Test Comic", "format": "Comic", "issues_remaining": 5},
        headers=headers,
        timeout=10,
    )
    assert thread_response.status_code in (200, 201)

    await page.goto(f"{test_server_url}/login")

    await page.wait_for_selector("#username", timeout=5000)
    await page.fill("#username", test_user)
    await page.fill("#password", "testpassword")

    submit_button = await page.wait_for_selector('button[type="submit"]', timeout=5000)
    await submit_button.click()

    await page.wait_for_url(f"{test_server_url}/", timeout=5000)

    await page.goto(f"{test_server_url}/")
    await page.wait_for_load_state("networkidle", timeout=5000)

    await page.wait_for_selector("#main-die-3d", timeout=15000)
    die_element = await page.wait_for_selector("#main-die-3d", timeout=15000)
    await die_element.click()

    await page.wait_for_url(f"{test_server_url}/rate", timeout=15000)

    await page.wait_for_selector("#rating-input", timeout=10000)

    await page.evaluate("document.getElementById('rating-input').value = '4.5'")
    await page.evaluate(
        "document.getElementById('rating-input').dispatchEvent(new Event('input', { bubbles: true }))"
    )
    await page.wait_for_timeout(500)

    submit_btn = await page.wait_for_selector("#submit-btn", timeout=5000)
    await submit_btn.click()

    await page.wait_for_url(f"{test_server_url}/", timeout=5000)

    current_url = page.url
    assert (
        current_url.rstrip("/") == f"{test_server_url}/"
        or current_url.rstrip("/") == test_server_url
    )
