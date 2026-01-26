"""Playwright E2E demo for thread repositioning features."""

import json
import time
import pytest
import requests
from sqlalchemy.orm import Session
from collections.abc import Generator
from playwright.sync_api import Page


@pytest.fixture(scope="function")
def test_user_with_spider_man(db: Session) -> Generator[tuple[str, int, int]]:
    """Create test user with Spider-Man thread for repositioning demo.

    Args:
        db: Database session for creating test data.

    Yields:
        A tuple containing (test_email, user_id, spider_thread_id).
    """
    from app.auth import hash_password
    from app.database import get_db
    from app.main import app
    from app.models import Thread, User
    from sqlalchemy import text

    db.execute(text("SELECT setval('users_id_seq', (SELECT COALESCE(MAX(id), 0) FROM users))"))
    db.commit()

    test_timestamp = int(time.time() * 1000)
    test_email = f"spider_demo_{test_timestamp}@example.com"

    user = User(
        username=test_email,
        email=test_email,
        password_hash=hash_password("testpassword"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Create Spider-Man Adventures thread
    spider_man_thread = Thread(
        title="Spider-Man Adventures",
        format="Comic",
        issues_remaining=50,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(spider_man_thread)
    db.flush()
    spider_thread_id = spider_man_thread.id
    db.commit()

    def override_get_db() -> Generator[Session]:
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    yield test_email, user.id, spider_thread_id

    app.dependency_overrides.clear()


def login_with_test_user(page: Page, test_server_url: str, email: str, password: str) -> None:
    """Helper function to login via browser using test user.

    Args:
        page: Playwright page object.
        test_server_url: Base URL of the test server.
        email: User email for authentication.
        password: User password for authentication.

    Returns:
        None
    """
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


@pytest.mark.integration
def test_thread_repositioning_fix_demo(
    browser_page: Page, test_server_url: str, test_user_with_spider_man: tuple[str, int, int]
) -> None:
    """Demo test showing thread repositioning fix working correctly."""
    page = browser_page
    test_email, _user_id, spider_thread_id = test_user_with_spider_man

    print("\n" + "=" * 80)
    print("THREAD REPOSITIONING FIX DEMO")
    print("=" * 80)

    # Login
    login_with_test_user(page, test_server_url, test_email, "testpassword")
    print(f"✅ Logged in as {test_email}")

    # Navigate to queue page
    page.goto(f"{test_server_url}/queue")
    page.wait_for_load_state("networkidle", timeout=5000)
    print("✅ Navigated to queue page")

    # Get initial position of Spider-Man thread
    headers = {"Authorization": f"Bearer {page.evaluate('localStorage.getItem("auth_token")')}"}
    thread_response = requests.get(
        f"{test_server_url}/api/threads/{spider_thread_id}",
        headers=headers,
        timeout=10,
    )
    assert thread_response.status_code == 200
    initial_position = thread_response.json()["queue_position"]
    print(f"✅ Spider-Man Adventures thread at initial position: {initial_position}")

    # Move thread to position 11
    print("\n🔄 Moving Spider-Man Adventures to position 11...")
    reposition_response = requests.put(
        f"{test_server_url}/api/threads/{spider_thread_id}/position/",
        json={"new_position": 11},
        headers=headers,
        timeout=10,
    )

    if reposition_response.status_code == 422:
        print("❌ 422 Validation Error - The original issue persists!")
        raise AssertionError(f"Repositioning failed with 422: {reposition_response.text}")
    elif reposition_response.status_code == 200:
        print("✅ SUCCESS! No 422 error - the fix is working!")
        result = reposition_response.json()
        print(f"🎉 Thread repositioned successfully: {result}")
    else:
        print(f"⚠️ Unexpected response: {reposition_response.status_code}")
        raise AssertionError(f"Unexpected status code: {reposition_response.status_code}")

    # Verify thread is now at position 11
    verify_response = requests.get(
        f"{test_server_url}/api/threads/{spider_thread_id}",
        headers=headers,
        timeout=10,
    )
    assert verify_response.status_code == 200
    final_position = verify_response.json()["queue_position"]
    assert final_position == 11, f"Expected position 11, got {final_position}"
    print(f"✅ VERIFIED: Spider-Man Adventures is now at position {final_position}")

    # Check queue integrity
    queue_response = requests.get(f"{test_server_url}/api/threads/", headers=headers, timeout=10)
    assert queue_response.status_code == 200
    queue_data = queue_response.json()
    active_threads = [t for t in queue_data if t["status"] == "active"]
    positions = [t["queue_position"] for t in active_threads]
    positions_sorted = sorted(positions)
    expected_positions = list(range(1, len(positions_sorted) + 1))
    assert positions_sorted == expected_positions, (
        f"Queue integrity issue: {positions_sorted} != {expected_positions}"
    )
    print(f"✅ Queue integrity maintained: {len(active_threads)} threads with sequential positions")

    print("\n🎉 THREAD REPOSITIONING FIX DEMO COMPLETED SUCCESSFULLY!")
    print("=" * 80)


@pytest.mark.integration
def test_thread_repositioning_edge_cases(
    browser_page: Page, test_server_url: str, test_user_with_spider_man: tuple[str, int, int]
) -> None:
    """Test edge cases for thread repositioning."""
    page = browser_page
    test_email, _user_id, spider_thread_id = test_user_with_spider_man

    print("\n" + "=" * 80)
    print("THREAD REPOSITIONING EDGE CASES TEST")
    print("=" * 80)

    # Login
    login_with_test_user(page, test_server_url, test_email, "testpassword")
    print(f"✅ Logged in as {test_email}")

    headers = {"Authorization": f"Bearer {page.evaluate('localStorage.getItem("auth_token")')}"}

    # Get queue count
    queue_response = requests.get(f"{test_server_url}/api/threads/", headers=headers, timeout=10)
    assert queue_response.status_code == 200
    queue_data = queue_response.json()
    active_count = len([t for t in queue_data if t["status"] == "active"])
    print(f"✅ Active threads in queue: {active_count}")

    # Test Case 1: Move to position 1 (front)
    print("\n📍 Test Case 1: Move to front (position 1)")
    response = requests.put(
        f"{test_server_url}/api/threads/{spider_thread_id}/position/",
        json={"new_position": 1},
        headers=headers,
        timeout=10,
    )
    assert response.status_code == 200
    verify_response = requests.get(
        f"{test_server_url}/api/threads/{spider_thread_id}",
        headers=headers,
        timeout=10,
    )
    assert verify_response.json()["queue_position"] == 1
    print("✅ Thread moved to position 1 successfully")

    # Test Case 2: Move to last position (back)
    print(f"\n📍 Test Case 2: Move to back (position {active_count})")
    response = requests.put(
        f"{test_server_url}/api/threads/{spider_thread_id}/position/",
        json={"new_position": active_count},
        headers=headers,
        timeout=10,
    )
    assert response.status_code == 200
    verify_response = requests.get(
        f"{test_server_url}/api/threads/{spider_thread_id}",
        headers=headers,
        timeout=10,
    )
    assert verify_response.json()["queue_position"] == active_count
    print(f"✅ Thread moved to position {active_count} successfully")

    # Test Case 3: Move to middle position
    middle_position = max(1, active_count // 2)
    print(f"\n📍 Test Case 3: Move to middle position ({middle_position})")
    response = requests.put(
        f"{test_server_url}/api/threads/{spider_thread_id}/position/",
        json={"new_position": middle_position},
        headers=headers,
        timeout=10,
    )
    assert response.status_code == 200
    verify_response = requests.get(
        f"{test_server_url}/api/threads/{spider_thread_id}",
        headers=headers,
        timeout=10,
    )
    assert verify_response.json()["queue_position"] == middle_position
    print(f"✅ Thread moved to position {middle_position} successfully")

    # Test Case 4: Invalid position (0 or negative)
    print("\n📍 Test Case 4: Invalid position (should fail)")
    response = requests.put(
        f"{test_server_url}/api/threads/{spider_thread_id}/position/",
        json={"new_position": 0},
        headers=headers,
        timeout=10,
    )
    assert response.status_code == 422
    print("✅ Correctly rejected invalid position 0")

    # Test Case 5: Position beyond queue size
    print(f"\n📍 Test Case 5: Position beyond queue size ({active_count + 10})")
    response = requests.put(
        f"{test_server_url}/api/threads/{spider_thread_id}/position/",
        json={"new_position": active_count + 10},
        headers=headers,
        timeout=10,
    )
    # This should either succeed (move to back) or fail with 422
    if response.status_code == 200:
        verify_response = requests.get(
            f"{test_server_url}/api/threads/{spider_thread_id}",
            headers=headers,
            timeout=10,
        )
        assert verify_response.json()["queue_position"] == active_count
        print(f"✅ Position clamped to back of queue ({active_count})")
    elif response.status_code == 422:
        print("✅ Correctly rejected position beyond queue size")
    else:
        raise AssertionError(f"Unexpected status code: {response.status_code}")

    print("\n🎉 ALL EDGE CASE TESTS PASSED!")
    print("=" * 80)
