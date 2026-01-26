#!/usr/bin/env python3
"""Playwright test demonstrating thread repositioning API fix working."""

import requests
import json
import time
import sys


def test_thread_repositioning_api():
    """Test the thread repositioning API directly to show the fix works."""

    # Test server URL (would normally be running)
    base_url = "http://127.0.0.1:8000"

    print("🎭 THREAD REPOSITIONING API FIX DEMONSTRATION")
    print("=" * 50)

    # First, let's check if the main application is running
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        if response.status_code != 200:
            print("❌ Application not running, starting it...")
            print("📝 Please start the application with: make dev")
            return False
    except requests.exceptions.ConnectionError:
        print("❌ Application not running, starting it...")
        print("📝 Please start the application with: make dev")
        return False

    print("✅ Application is running")

    # Login as test user
    print("\n📍 STEP 1: Login as test user")
    login_response = requests.post(
        f"{base_url}/api/auth/login",
        json={"username": "testuser123", "password": "testpassword"},
        timeout=10,
    )

    if login_response.status_code != 200:
        print(f"❌ Login failed: {login_response.status_code}")
        print(f"Response: {login_response.text}")
        return False

    access_token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    print("✅ Login successful")

    # Get threads to find Spider-Man Adventures
    print("\n📍 STEP 2: Get threads and find Spider-Man Adventures")
    threads_response = requests.get(f"{base_url}/api/threads/", headers=headers, timeout=10)

    if threads_response.status_code != 200:
        print(f"❌ Failed to get threads: {threads_response.status_code}")
        return False

    threads = threads_response.json()
    spider_man_thread = None

    for thread in threads:
        if thread["title"] == "Spider-Man Adventures":
            spider_man_thread = thread
            break

    if not spider_man_thread:
        print("❌ Spider-Man Adventures thread not found")
        print("Available threads:")
        for thread in threads[:5]:  # Show first 5 threads
            print(
                f"  - {thread['title']} (ID: {thread['id']}, Position: {thread['queue_position']})"
            )
        return False

    thread_id = spider_man_thread["id"]
    initial_position = spider_man_thread["queue_position"]
    print(f"✅ Found Spider-Man Adventures at position {initial_position} (ID: {thread_id})")

    # Attempt to move to position 11 (the original failing scenario)
    print(
        f"\n📍 STEP 3: Move Spider-Man Adventures from position {initial_position} to position 11"
    )
    print("🔄 This is the operation that previously failed with 422 error...")

    reposition_response = requests.put(
        f"{base_url}/api/threads/{thread_id}/position",
        json={"new_position": 11},
        headers=headers,
        timeout=10,
    )

    print(f"🔄 API Response Status: {reposition_response.status_code}")

    if reposition_response.status_code == 422:
        print("❌ 422 Validation Error - The original issue persists!")
        print(f"Response: {reposition_response.text}")
        return False
    elif reposition_response.status_code == 200:
        print("✅ SUCCESS! No 422 error - the fix is working!")
        result = reposition_response.json()
        print(f"🎉 Thread repositioned successfully: {result}")
    else:
        print(f"⚠️ Unexpected response: {reposition_response.status_code}")
        print(f"Response: {reposition_response.text}")
        return False

    # Verify the thread is now at position 11
    print(f"\n📍 STEP 4: Verify Spider-Man Adventures is now at position 11")
    verify_response = requests.get(
        f"{base_url}/api/threads/{thread_id}", headers=headers, timeout=10
    )

    if verify_response.status_code != 200:
        print(f"❌ Failed to verify thread: {verify_response.status_code}")
        return False

    updated_thread = verify_response.json()
    final_position = updated_thread["queue_position"]

    if final_position == 11:
        print(f"✅ VERIFIED: Spider-Man Adventures is now at position {final_position}")
    else:
        print(f"❌ UNEXPECTED: Expected position 11, but got position {final_position}")
        return False

    # Check queue integrity
    print(f"\n📍 STEP 5: Verify queue integrity")
    queue_response = requests.get(f"{base_url}/api/threads/", headers=headers, timeout=10)

    if queue_response.status_code != 200:
        print(f"❌ Failed to get queue: {queue_response.status_code}")
        return False

    queue_data = queue_response.json()
    active_threads = [t for t in queue_data if t["status"] == "active"]
    positions = [t["queue_position"] for t in active_threads]
    positions_sorted = sorted(positions)
    expected_positions = list(range(1, len(positions_sorted) + 1))

    if positions_sorted == expected_positions:
        print(
            f"✅ Queue integrity maintained: {len(active_threads)} threads with sequential positions 1-{len(active_threads)}"
        )
    else:
        print(f"❌ Queue integrity issue: {positions_sorted} != {expected_positions}")
        return False

    # Test results
    print("\n🎉 THREAD REPOSITIONING FIX DEMO COMPLETED SUCCESSFULLY!")
    print("=" * 60)
    print("📋 Summary:")
    print(f"   - Spider-Man Adventures moved from position {initial_position} to position 11")
    print("   - No 422 validation error occurred")
    print("   - Thread is now correctly positioned")
    print("   - Queue integrity maintained")
    print("   - 🎯 The original issue has been RESOLVED!")

    return True


if __name__ == "__main__":
    success = test_thread_repositioning_api()
    sys.exit(0 if success else 1)
