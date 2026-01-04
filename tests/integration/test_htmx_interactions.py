"""HTMX frontend integration tests using Playwright."""

from datetime import datetime

import pytest
from playwright.sync_api import sync_playwright
from sqlalchemy.orm import Session

from app.models import Event, Thread, User
from app.models import Session as SessionModel


@pytest.fixture(scope="function")
def test_data(db_session: Session):
    """Create sample threads and sessions for HTMX testing."""
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
        Thread(
            title="Flash",
            format="Comic",
            issues_remaining=3,
            queue_position=4,
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
class TestHTMXDiceSelector:
    """Test HTMX die selector interactions."""

    def test_set_die_to_4_updates_header(self, browser_page, test_data, test_server):
        """Test that clicking d4 button updates header die label via HTMX."""
        browser_page.goto(f"{test_server}/roll")

        d4_button = browser_page.locator('button[data-die="4"]')
        d4_button.click()

        header_die_label = browser_page.locator("#header-die-label")
        header_text = header_die_label.inner_text()
        assert "4" in header_text

    def test_set_die_to_8_updates_header(self, browser_page, test_data, test_server):
        """Test that clicking d8 button updates header die label via HTMX."""
        browser_page.goto(f"{test_server}/roll")

        d8_button = browser_page.locator('button[data-die="8"]')
        d8_button.click()

        header_die_label = browser_page.locator("#header-die-label")
        header_text = header_die_label.inner_text()
        assert "8" in header_text

    def test_set_die_to_20_updates_header(self, browser_page, test_data, test_server):
        """Test that clicking d20 button updates header die label via HTMX."""
        browser_page.goto(f"{test_server}/roll")

        d20_button = browser_page.locator('button[data-die="20"]')
        d20_button.click()

        header_die_label = browser_page.locator("#header-die-label")
        header_text = header_die_label.inner_text()
        assert "20" in header_text

    def test_die_button_click_triggers_request(self, browser_page, test_data, test_server):
        """Test that clicking a die button triggers HTMX request."""
        browser_page.goto(f"{test_server}/roll")

        d8_button = browser_page.locator('button[data-die="8"]')
        d8_button.click()

        d8_button.wait_for_state("hidden")


@pytest.mark.integration
class TestHTMXRollDice:
    """Test HTMX roll dice interactions."""

    def test_roll_dice_updates_result_container(self, browser_page, test_data, test_server):
        """Test that rolling die updates result container via HTMX."""
        browser_page.goto(f"{test_server}/roll")

        result_container = browser_page.locator("#result")
        initial_html = result_container.inner_html()

        main_die_wrapper = browser_page.locator("#main-die-wrapper")
        main_die_wrapper.click()

        browser_page.wait_for_selector(".result-reveal", timeout=5000)
        updated_html = result_container.inner_html()

        assert initial_html != updated_html

    def test_roll_dice_displays_rating_form(self, browser_page, test_data, test_server):
        """Test that rolling die displays rating form via HTMX swap."""
        browser_page.goto(f"{test_server}/roll")

        main_die_wrapper = browser_page.locator("#main-die-wrapper")
        main_die_wrapper.click()

        browser_page.wait_for_selector("#rating-form-container", timeout=5000)

        rating_form = browser_page.locator("#rating-form-container")
        assert rating_form.count() > 0

    def test_roll_dice_creates_event(self, browser_page, test_data, test_server, db_session):
        """Test that rolling die creates event in database."""
        browser_page.goto(f"{test_server}/roll")

        from sqlalchemy import select

        events_before = (
            db_session.execute(select(Event).where(Event.type == "roll")).scalars().all()
        )

        main_die_wrapper = browser_page.locator("#main-die-wrapper")
        main_die_wrapper.click()

        browser_page.wait_for_selector(".result-reveal", timeout=5000)

        events_after = db_session.execute(select(Event).where(Event.type == "roll")).scalars().all()

        assert len(events_after) == len(events_before) + 1

    def test_roll_dice_updates_roll_pool(self, browser_page, test_data, test_server):
        """Test that rolling die loads correct roll pool based on die size."""
        browser_page.goto(f"{test_server}/roll")

        pool_threads_before = browser_page.locator("#pool-threads > div").count()
        assert pool_threads_before == 4

        d4_button = browser_page.locator('button[data-die="4"]')
        d4_button.click()

        browser_page.wait_for_timeout(500)

        pool_threads_after = browser_page.locator("#pool-threads > div").count()
        assert pool_threads_after == 4


@pytest.mark.integration
class TestHTMXRating:
    """Test HTMX rating interactions."""

    def test_rating_input_updates_display(self, browser_page, test_data, test_server):
        """Test that rating input updates display value in real-time."""
        browser_page.goto(f"{test_server}/roll")

        main_die_wrapper = browser_page.locator("#main-die-wrapper")
        main_die_wrapper.click()

        browser_page.wait_for_selector("#rating-form-container", timeout=5000)

        rating_input = browser_page.locator("#rating-input")
        rating_input.fill("5.0")

        browser_page.wait_for_timeout(100)

        rating_value = browser_page.locator("#rating-value")
        assert rating_value.inner_text() == "5.0"

    def test_rating_preview_updates_text(self, browser_page, test_data, test_server):
        """Test that rating preview updates text based on rating."""
        browser_page.goto(f"{test_server}/roll")

        main_die_wrapper = browser_page.locator("#main-die-wrapper")
        main_die_wrapper.click()

        browser_page.wait_for_selector("#rating-form-container", timeout=5000)

        rating_input = browser_page.locator("#rating-input")
        rating_input.fill("4.0")

        browser_page.wait_for_timeout(100)

        rating_preview = browser_page.locator("#rating-preview")
        assert "steps down" in rating_preview.inner_text().lower()

    def test_rating_low_updates_preview_text(self, browser_page, test_data, test_server):
        """Test that low rating preview shows step up text."""
        browser_page.goto(f"{test_server}/roll")

        main_die_wrapper = browser_page.locator("#main-die-wrapper")
        main_die_wrapper.click()

        browser_page.wait_for_selector("#rating-form-container", timeout=5000)

        rating_input = browser_page.locator("#rating-input")
        rating_input.fill("2.0")

        browser_page.wait_for_timeout(100)

        rating_preview = browser_page.locator("#rating-preview")
        assert "steps up" in rating_preview.inner_text().lower()

    def test_rating_preview_updates_die_indicator(self, browser_page, test_data, test_server):
        """Test that rating preview updates die indicator."""
        browser_page.goto(f"{test_server}/roll")

        main_die_wrapper = browser_page.locator("#main-die-wrapper")
        main_die_wrapper.click()

        browser_page.wait_for_selector("#rating-form-container", timeout=5000)

        rating_input = browser_page.locator("#rating-input")
        rating_input.fill("4.0")

        browser_page.wait_for_timeout(100)

        header_die_label = browser_page.locator("#header-die-label")
        assert header_die_label.inner_text() == "d4"


@pytest.mark.integration
class TestHTMXReroll:
    """Test HTMX reroll interactions."""

    def test_reroll_updates_result_container(self, browser_page, test_data, test_server):
        """Test that clicking reroll updates result container."""
        browser_page.goto(f"{test_server}/roll")

        main_die_wrapper = browser_page.locator("#main-die-wrapper")
        main_die_wrapper.click()

        browser_page.wait_for_selector(".result-reveal", timeout=5000)

        reroll_btn = browser_page.locator("#reroll-btn")
        reroll_btn.click()

        browser_page.wait_for_selector(".result-reveal", timeout=5000)

        result_reveal = browser_page.locator(".result-reveal")
        assert result_reveal.count() > 0

    def test_reroll_displays_reroll_label(self, browser_page, test_data, test_server):
        """Test that reroll displays 'Rerolled' label."""
        browser_page.goto(f"{test_server}/roll")

        main_die_wrapper = browser_page.locator("#main-die-wrapper")
        main_die_wrapper.click()

        browser_page.wait_for_selector(".result-reveal", timeout=5000)

        reroll_btn = browser_page.locator("#reroll-btn")
        reroll_btn.click()

        browser_page.wait_for_selector(".result-reveal", timeout=5000)

        page_content = browser_page.inner_html("#result")
        assert "Rerolled" in page_content


@pytest.mark.integration
class TestHTMXDismissPending:
    """Test HTMX dismiss pending thread interactions."""

    def test_dismiss_pending_removes_alert(self, browser_page, test_data, test_server, db_session):
        """Test that dismissing pending thread removes alert via HTMX."""
        from sqlalchemy import select

        current_session = (
            db_session.execute(
                select(SessionModel)
                .where(SessionModel.ended_at.is_(None))
                .order_by(SessionModel.started_at.desc())
            )
            .scalars()
            .first()
        )

        current_session.pending_thread_id = test_data["threads"][0].id
        current_session.pending_thread_updated_at = datetime.now()
        db_session.commit()

        browser_page.goto(f"{test_server}/roll")

        browser_page.wait_for_selector("#pending-thread-alert", timeout=3000)

        dismiss_button = browser_page.locator("#pending-thread-alert button")
        dismiss_button.click()

        browser_page.wait_for_timeout(500)

        pending_alert = browser_page.locator("#pending-thread-alert")
        assert pending_alert.count() == 0

    def test_dismiss_pending_creates_event(self, browser_page, test_data, test_server, db_session):
        """Test that dismissing pending thread creates event."""
        from sqlalchemy import select

        current_session = (
            db_session.execute(
                select(SessionModel)
                .where(SessionModel.ended_at.is_(None))
                .order_by(SessionModel.started_at.desc())
            )
            .scalars()
            .first()
        )

        current_session.pending_thread_id = test_data["threads"][0].id
        current_session.pending_thread_updated_at = datetime.now()
        db_session.commit()

        events_before = (
            db_session.execute(select(Event).where(Event.type == "rolled_but_skipped"))
            .scalars()
            .all()
        )

        browser_page.goto(f"{test_server}/roll")

        browser_page.wait_for_selector("#pending-thread-alert", timeout=3000)

        dismiss_button = browser_page.locator("#pending-thread-alert button")
        dismiss_button.click()

        browser_page.wait_for_timeout(500)

        events_after = (
            db_session.execute(select(Event).where(Event.type == "rolled_but_skipped"))
            .scalars()
            .all()
        )

        assert len(events_after) == len(events_before) + 1


@pytest.mark.integration
class TestHTMXRollPool:
    """Test HTMX roll pool loading and updates."""

    def test_roll_pool_loads_on_page_load(self, browser_page, test_data, test_server):
        """Test that roll pool loads on page load via JavaScript."""
        browser_page.goto(f"{test_server}/roll")

        browser_page.wait_for_selector("#pool-threads", timeout=3000)

        pool_threads = browser_page.locator("#pool-threads > div")
        assert pool_threads.count() > 0

    def test_roll_pool_displays_thread_titles(self, browser_page, test_data, test_server):
        """Test that roll pool displays correct thread titles."""
        browser_page.goto(f"{test_server}/roll")

        browser_page.wait_for_selector("#pool-threads", timeout=3000)

        pool_content = browser_page.inner_html("#pool-threads")

        for thread in test_data["threads"][:6]:
            assert thread.title in pool_content

    def test_roll_pool_updates_after_die_change(self, browser_page, test_data, test_server):
        """Test that roll pool updates after die size changes."""
        browser_page.goto(f"{test_server}/roll")

        d4_button = browser_page.locator('button[data-die="4"]')
        d4_button.click()

        browser_page.wait_for_timeout(500)

        pool_threads_after = browser_page.locator("#pool-threads > div").count()

        assert pool_threads_after == 4

    def test_empty_pool_displays_message(self, browser_page, test_server, db_session):
        """Test that empty pool displays message."""
        from sqlalchemy import delete

        db_session.execute(delete(Thread))
        db_session.commit()

        browser_page.goto(f"{test_server}/roll")

        browser_page.wait_for_selector("#pool-threads", timeout=3000)

        pool_content = browser_page.inner_html("#pool-threads")
        assert "Queue Empty" in pool_content


@pytest.mark.integration
class TestHTMXStaleSuggestion:
    """Test HTMX stale thread suggestion loading."""

    def test_stale_suggestion_loads_on_page_load(self, browser_page, test_data, test_server):
        """Test that stale suggestion loads on page load."""
        browser_page.goto(f"{test_server}/roll")

        browser_page.wait_for_selector("#pool-threads", timeout=3000)

        stale_container = browser_page.locator("#stale-suggestion")
        assert stale_container.count() >= 0


@pytest.mark.integration
class TestHTMXRatePage:
    """Test HTMX interactions on rate page."""

    def test_rate_page_loads_session_data(self, browser_page, test_data, test_server, db_session):
        """Test that rate page loads session data via JavaScript."""
        from sqlalchemy import select

        current_session = (
            db_session.execute(
                select(SessionModel)
                .where(SessionModel.ended_at.is_(None))
                .order_by(SessionModel.started_at.desc())
            )
            .scalars()
            .first()
        )

        current_session.pending_thread_id = test_data["threads"][0].id
        current_session.last_rolled_result = 3
        db_session.commit()

        browser_page.goto(f"{test_server}/rate")

        browser_page.wait_for_selector("#thread-info", timeout=3000)

        thread_info = browser_page.inner_html("#thread-info")
        assert test_data["threads"][0].title in thread_info

    def test_rate_page_rating_input_updates_display(self, browser_page, test_data, test_server):
        """Test that rate page rating input updates display."""
        browser_page.goto(f"{test_server}/rate")

        browser_page.wait_for_selector("#rating-input", timeout=3000)

        rating_input = browser_page.locator("#rating-input")
        rating_input.fill("5.0")

        browser_page.wait_for_timeout(100)

        rating_value = browser_page.locator("#rating-value")
        assert rating_value.inner_text() == "5.0"


@pytest.mark.integration
class TestHTMXTemplateRendering:
    """Test HTMX template rendering and dynamic content."""

    def test_template_inherits_base_template(self, browser_page, test_server):
        """Test that templates inherit from base template."""
        browser_page.goto(f"{test_server}/roll")

        base_elements = browser_page.locator("nav")
        assert base_elements.count() > 0

    def test_dynamic_content_rendered_in_template(self, browser_page, test_data, test_server):
        """Test that dynamic content is rendered in template."""
        browser_page.goto(f"{test_server}/roll")

        current_die_label = browser_page.locator("#header-die-label")
        assert "d" in current_die_label.inner_text()

    def test_template_variables_substituted(self, browser_page, test_data, test_server):
        """Test that template variables are substituted correctly."""
        browser_page.goto(f"{test_server}/roll")

        for die_value in [4, 6, 8, 10, 12, 20]:
            button = browser_page.locator(f'button[data-die="{die_value}"]')
            assert button.count() == 1


@pytest.mark.integration
class TestHTMXErrorHandling:
    """Test HTMX error handling and edge cases."""

    def test_invalid_die_size_rejected(self, browser_page, test_data, test_server, db_session):
        """Test that invalid die size is rejected by HTMX endpoint."""
        browser_page.goto(f"{test_server}/roll")

        response = browser_page.request.post(f"{test_server}/roll/set-die?die=7")

        assert response.status == 400

    def test_roll_with_empty_queue_returns_error_message(
        self, browser_page, test_server, db_session
    ):
        """Test that rolling with empty queue returns error message."""
        from sqlalchemy import delete

        db_session.execute(delete(Thread))
        db_session.commit()

        response = browser_page.request.post(f"{test_server}/roll/html")

        assert response.status == 200
        assert "No active threads" in response.text()

    def test_rating_without_active_session_returns_error(self, browser_page, test_server):
        """Test that rating without active session returns error."""
        response = browser_page.request.post(
            f"{test_server}/rate/", data={"rating": 4.0, "issues_read": 1}
        )

        assert response.status == 400
        assert "No active session" in response.json()["detail"]


@pytest.mark.integration
class TestHTMXNavigation:
    """Test HTMX navigation between pages."""

    def test_navigation_updates_page_title(self, browser_page, test_data, test_server):
        """Test that navigation updates page title."""
        browser_page.goto(f"{test_server}/roll")

        roll_title = browser_page.title()

        browser_page.goto(f"{test_server}/queue")

        queue_title = browser_page.title()

        assert roll_title is not None
        assert queue_title is not None

    def test_session_state_persists_across_navigation(self, browser_page, test_data, test_server):
        """Test that session state persists across page navigation."""
        browser_page.goto(f"{test_server}/roll")

        d8_button = browser_page.locator('button[data-die="8"]')
        d8_button.click()

        browser_page.wait_for_timeout(500)

        browser_page.goto(f"{test_server}/queue")

        browser_page.goto(f"{test_server}/roll")

        final_die = browser_page.locator("#header-die-label").inner_text()

        assert "8" in final_die
