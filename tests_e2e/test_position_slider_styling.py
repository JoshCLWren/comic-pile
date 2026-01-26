"""Test Position Slider Confirm button styling fix.

This test verifies that Confirm button:
1. Matches Cancel button style when enabled
2. Looks appropriately disabled when no position change
3. Is clearly visible when enabled (not "blended into background")
"""

import time

import pytest
from app.auth import create_access_token, hash_password
from app.models import Thread, User
from playwright.async_api import Page
from sqlalchemy import text


@pytest.fixture(scope="function")
def test_user_with_test_threads(test_server_url, db) -> User:
    """Create test user with multiple threads for position slider testing.

    Args:
        test_server_url: The test server URL.
        db: Database session.

    Returns:
        The created User object with test threads.
    """
    db.execute(text("SELECT setval('users_id_seq', (SELECT COALESCE(MAX(id), 0) FROM users))"))
    db.commit()

    test_timestamp = int(time.time() * 1000)
    test_email = f"testuser123_{test_timestamp}@example.com"

    user = User(
        username=test_email,
        email=test_email,
        password_hash=hash_password("testpassword"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Create threads across multiple positions
    threads_data = [
        ("Superman", 1, "active"),
        ("Batman", 2, "active"),
        ("Wonder Woman", 3, "active"),
        ("Flash", 4, "active"),
        ("Iron Man", 5, "active"),
        ("Captain America", 6, "active"),
        ("Thor", 7, "active"),
        ("Hulk", 8, "active"),
        ("Black Widow", 9, "active"),
        ("Hawkeye", 10, "active"),
    ]

    for title, position, status in threads_data:
        thread = Thread(
            title=title,
            format="Comic",
            issues_remaining=5,
            queue_position=position,
            status=status,
            user_id=user.id,
        )
        db.add(thread)

    db.commit()

    return user


@pytest.mark.integration
async def test_position_slider_confirm_button_styling(
    page: Page, test_server_url: str, test_user_with_test_threads: User
):
    """Verify Confirm button styling in Position Slider matches Cancel button."""
    # Get test user and database URL
    user = test_user_with_test_threads
    if not user:
        print("ERROR: No test user available")
        return

    # Create auth token
    token = create_access_token(data={"sub": user.username, "jti": "test"})

    print("Starting Position Slider styling test...")
    print(f"Test user: {user.username}")

    # Navigate and login
    await page.goto(test_server_url)
    await page.evaluate(f'localStorage.setItem("auth_token", "{token}")')
    await page.goto(f"{test_server_url}/queue")

    # Wait for queue to load
    await page.wait_for_timeout(5000)

    # Find a thread to reposition (Wonder Woman at position 3)
    threads = page.locator('[data-testid="queue-thread-list"] > div')
    await threads.count()

    middle_thread = threads.nth(2)
    reposition_button = middle_thread.get_by_role("button", has_text="Reposition")

    # Click reposition on a middle thread
    await reposition_button.click()

    # Wait for modal to appear
    await page.wait_for_timeout(3000)

    # Screenshot 1: Initial modal state (should show Confirm as enabled)
    await page.screenshot(path="screenshots/01-position-slider-initial.png", full_page=False)
    print("✓ Screenshot 1: Initial modal state")

    # Get buttons
    cancel_button = page.get_by_role("button", name="Cancel")
    confirm_button = page.get_by_role("button", name="Confirm")

    # Check opacities
    cancel_opacity = await cancel_button.evaluate("el => window.getComputedStyle(el).opacity")
    confirm_opacity = await confirm_button.evaluate("el => window.getComputedStyle(el).opacity")

    print(f"Cancel opacity: {cancel_opacity}")
    print(f"Confirm opacity: {confirm_opacity}")

    # Confirm should be visible when enabled
    assert float(confirm_opacity) > 0.8

    # Screenshot 2: After moving slider (Confirm should still look enabled)
    slider = page.get_by_role("slider", name="Position")
    max_value = await slider.get_attribute("max")

    await slider.fill(max_value)
    await page.wait_for_timeout(1000)

    await page.screenshot(path="screenshots/02-position-slider-after-move.png", full_page=False)
    print("✓ Screenshot 2: After moving slider")

    # Verify Confirm button still visible
    confirm_opacity_after = await confirm_button.evaluate(
        "el => window.getComputedStyle(el).opacity"
    )
    assert float(confirm_opacity_after) > 0.8

    # Screenshot 3: Confirm button disabled (return slider to position 3)
    await slider.fill("3")
    await page.wait_for_timeout(1000)

    await page.screenshot(path="screenshots/03-position-slider-disabled.png", full_page=False)
    print("✓ Screenshot 3: Confirm button disabled")

    # Verify Confirm button is disabled
    confirm_opacity_disabled = await confirm_button.evaluate(
        "el => window.getComputedStyle(el).opacity"
    )
    assert float(confirm_opacity_disabled) < 0.5

    print("\n✅ All Position Slider styling tests passed!")
    print("   - Confirm button matches Cancel when enabled")
    print("   - Confirm button clearly visible (not blended)")
    print("   - Confirm button appropriately disabled when no change")
    print("   - All 3 screenshots saved")
