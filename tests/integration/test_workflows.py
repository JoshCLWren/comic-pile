"""Playwright integration tests for comic-pile using direct API."""

from datetime import datetime

import pytest
from playwright.sync_api import sync_playwright
from sqlalchemy.orm import Session

from app.models import Session as SessionModel
from app.models import Thread, User


@pytest.fixture(scope="function")
def test_data(db_session: Session):
    """Create sample threads and sessions for testing."""
    user = User(username="test_user", created_at=datetime.now())
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    threads = [
        Thread(
            title="Superman",
            format="Comic",
            issues_remaining=10,
            queue_position=1,
            status="active",
            user_id=user.id,
            created_at=datetime.now(),
        ),
        Thread(
            title="Batman",
            format="Comic",
            issues_remaining=5,
            queue_position=2,
            status="active",
            user_id=user.id,
            created_at=datetime.now(),
        ),
        Thread(
            title="Wonder Woman",
            format="Comic",
            issues_remaining=8,
            queue_position=3,
            status="active",
            user_id=user.id,
            created_at=datetime.now(),
        ),
    ]

    for thread in threads:
        db_session.add(thread)
    db_session.commit()

    for thread in threads:
        db_session.refresh(thread)

    session = SessionModel(
        start_die=6,
        user_id=user.id,
        started_at=datetime.now(),
    )
    db_session.add(session)
    db_session.commit()

    return {"user": user, "threads": threads, "session": session}


@pytest.fixture(scope="function")
def browser_page(test_server):
    """Create a Playwright browser page for testing."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        yield page
        context.close()
        browser.close()


@pytest.mark.integration
class TestRollWorkflow:
    """Test roll dice workflow with performance assertions."""

    def test_page_load_performance(self, browser_page, test_server, db_session):
        """Test that roll page loads in reasonable time."""
        start_time = datetime.now()
        browser_page.goto(f"{test_server}/roll")
        load_time = (datetime.now() - start_time).total_seconds() * 1000

        assert load_time < 2000, f"Page load took {load_time}ms, expected < 2000ms"

    def test_roll_dice_performance(self, browser_page, test_data, test_server):
        """Test that roll operation completes in reasonable time."""
        browser_page.goto(f"{test_server}/roll")

        start_time = datetime.now()
        browser_page.click("#main-die-wrapper")

        browser_page.wait_for_selector("#rating-form-container", timeout=5000)
        roll_time = (datetime.now() - start_time).total_seconds() * 1000

        assert roll_time < 3000, f"Roll operation took {roll_time}ms, expected < 3000ms"

    def test_roll_displays_result(self, browser_page, test_data, test_server):
        """Test that rolling displays a result container."""
        browser_page.goto(f"{test_server}/roll")
        browser_page.click("#main-die-wrapper")
        browser_page.wait_for_selector("#rating-form-container", timeout=5000)

        result_container = browser_page.locator(".result-reveal")
        assert result_container.count() > 0


@pytest.mark.integration
class TestRatingWorkflow:
    """Test rating workflow with performance assertions."""

    def test_rating_performance(self, browser_page, test_data, test_server):
        """Test that rating operation completes in reasonable time."""
        browser_page.goto(f"{test_server}/roll")
        browser_page.click("#main-die-wrapper")
        browser_page.wait_for_selector("#rating-form-container", timeout=5000)

        start_time = datetime.now()
        browser_page.click("#submit-rating-btn")

        browser_page.wait_for_url("**/roll", timeout=5000)
        rating_time = (datetime.now() - start_time).total_seconds() * 1000

        assert rating_time < 2000, f"Rating operation took {rating_time}ms, expected < 2000ms"


@pytest.mark.integration
class TestQueueOperations:
    """Test queue operations."""

    def test_queue_page_loads(self, browser_page, test_data, test_server):
        """Test that queue page loads correctly."""
        browser_page.goto(f"{test_server}/queue")

        assert browser_page.title() is not None

    def test_queue_loads_quickly(self, browser_page, test_data, test_server):
        """Test that queue page loads quickly."""
        start_time = datetime.now()
        browser_page.goto(f"{test_server}/queue")
        browser_page.wait_for_load_state("networkidle", timeout=3000)
        load_time = (datetime.now() - start_time).total_seconds() * 1000

        assert load_time < 2000, f"Queue page took {load_time}ms, expected < 2000ms"


@pytest.mark.integration
class TestSessionManagement:
    """Test session management."""

    def test_session_display_on_roll_page(self, browser_page, test_data, test_server):
        """Test that session information is displayed on roll page."""
        browser_page.goto(f"{test_server}/roll")

        die_label = browser_page.text_content("#header-die-label")
        assert die_label is not None
        assert "d" in die_label

    def test_session_persistence(self, browser_page, test_data, test_server):
        """Test that session persists across page navigation."""
        browser_page.goto(f"{test_server}/roll")
        initial_die = browser_page.text_content("#header-die-label")

        browser_page.goto(f"{test_server}/queue")
        browser_page.goto(f"{test_server}/roll")

        final_die = browser_page.text_content("#header-die-label")

        assert initial_die == final_die

    def test_health_check_endpoint(self, browser_page, test_server):
        """Test health check endpoint responds quickly."""
        start_time = datetime.now()
        response = browser_page.request.get(f"{test_server}/health")
        response_time = (datetime.now() - start_time).total_seconds() * 1000

        assert response.status == 200
        assert response_time < 500, f"Health check took {response_time}ms, expected < 500ms"

        data = response.json()
        assert data["status"] == "healthy"
        assert data["database"] == "connected"


@pytest.mark.integration
class TestNavigation:
    """Test navigation between pages."""

    def test_all_pages_load(self, browser_page, test_server):
        """Test that all main pages load successfully."""
        pages = ["/", "/roll", "/queue", "/rate", "/history"]

        for path in pages:
            browser_page.goto(f"{test_server}{path}")
            browser_page.wait_for_load_state("networkidle", timeout=3000)
            assert browser_page.title() is not None


@pytest.mark.integration
class TestRollPool:
    """Test roll pool functionality."""

    def test_roll_pool_displays_threads(self, browser_page, test_data, test_server):
        """Test that roll pool displays threads."""
        browser_page.goto(f"{test_server}/roll")
        browser_page.wait_for_selector("#pool-threads", timeout=3000)

        pool_threads = browser_page.locator("#pool-threads > div").count()

        assert pool_threads > 0

    def test_roll_pool_loads_quickly(self, browser_page, test_data, test_server):
        """Test that roll pool loads quickly."""
        browser_page.goto(f"{test_server}/roll")

        start_time = datetime.now()
        browser_page.wait_for_selector("#pool-threads", timeout=3000)
        pool_load_time = (datetime.now() - start_time).total_seconds() * 1000

        assert pool_load_time < 500, f"Roll pool load took {pool_load_time}ms, expected < 500ms"


@pytest.mark.integration
class TestThreadCreationAPI:
    """Test thread creation via API."""

    def test_thread_creation_via_api(self, browser_page, test_server, db_session):
        """Test thread creation via API endpoint."""
        start_time = datetime.now()

        response = browser_page.request.post(
            f"{test_server}/threads/",
            data={
                "title": "API Test Comic",
                "format": "Comic",
                "issues_remaining": 8,
            },
        )
        creation_time = (datetime.now() - start_time).total_seconds() * 1000

        assert response.status == 201
        assert creation_time < 2000, (
            f"API thread creation took {creation_time}ms, expected < 2000ms"
        )

        thread_data = response.json()
        assert thread_data["title"] == "API Test Comic"
        assert thread_data["format"] == "Comic"
        assert thread_data["issues_remaining"] == 8

    def test_thread_list_api(self, browser_page, test_server, test_data):
        """Test that thread list API returns all test threads."""
        response = browser_page.request.get(f"{test_server}/threads/")

        assert response.status == 200

        threads = response.json()
        assert len(threads) >= len(test_data["threads"])

        thread_titles = [t["title"] for t in threads]
        for test_thread in test_data["threads"]:
            assert test_thread.title in thread_titles

    def test_thread_get_api(self, browser_page, test_server, test_data):
        """Test that single thread API returns correct thread."""
        test_thread = test_data["threads"][0]
        response = browser_page.request.get(f"{test_server}/threads/{test_thread.id}")

        assert response.status == 200

        thread_data = response.json()
        assert thread_data["title"] == test_thread.title
        assert thread_data["format"] == test_thread.format
        assert thread_data["issues_remaining"] == test_thread.issues_remaining


@pytest.mark.integration
class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_rating_validation(self, browser_page, test_data, test_server):
        """Test that rating input has correct validation attributes."""
        browser_page.goto(f"{test_server}/roll")
        browser_page.click("#main-die-wrapper")
        browser_page.wait_for_selector("#rating-form-container", timeout=5000)

        rating_input = browser_page.locator("#rating-input")

        min_value = rating_input.get_attribute("min")
        max_value = rating_input.get_attribute("max")
        step = rating_input.get_attribute("step")

        assert min_value == "0.5"
        assert max_value == "5.0"
        assert step == "0.5"


@pytest.mark.integration
class TestQueueAPI:
    """Test queue operations via API."""

    def test_move_to_front_api(self, browser_page, test_server, test_data):
        """Test moving thread to front via API."""
        test_thread = test_data["threads"][2]

        response = browser_page.request.put(f"{test_server}/queue/threads/{test_thread.id}/front/")

        assert response.status == 200

        thread_data = response.json()
        assert thread_data["position"] == 1

    def test_move_to_back_api(self, browser_page, test_server, test_data):
        """Test moving thread to back via API."""
        test_thread = test_data["threads"][0]

        response = browser_page.request.put(f"{test_server}/queue/threads/{test_thread.id}/back/")

        assert response.status == 200

        thread_data = response.json()
        assert thread_data["position"] > 1

    def test_move_to_position_api(self, browser_page, test_server, test_data):
        """Test moving thread to specific position via API."""
        test_thread = test_data["threads"][0]

        response = browser_page.request.put(
            f"{test_server}/queue/threads/{test_thread.id}/position/",
            data={"new_position": 2},
        )

        assert response.status == 200

        thread_data = response.json()
        assert thread_data["position"] == 2
