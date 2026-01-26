#!/usr/bin/env python3
"""Test the API endpoint with authentication."""

import requests

# First, let's try to login and get a token
login_data = {"username": "testuser123", "password": "testpass123"}

try:
    # Login to get token
    print("Attempting login...")
    login_response = requests.post("http://localhost:8000/api/auth/login", data=login_data)
    print(f"Login response: {login_response.status_code}")

    if login_response.status_code == 200:
        login_result = login_response.json()
        token = login_result.get("access_token")
        print(f"Token obtained: {token[:20]}...")

        # Now test the reposition API
        headers = {"Authorization": f"Bearer {token}"}
        reposition_data = {"new_position": 15}  # Move to a different position

        print("Moving thread 210 to position 15...")
        reposition_response = requests.put(
            "http://localhost:8000/api/queue/threads/210/position/",
            headers=headers,
            json=reposition_data,
        )

        print(f"Reposition response: {reposition_response.status_code}")
        print(f"Response: {reposition_response.text}")

        if reposition_response.status_code == 200:
            result = reposition_response.json()
            print(f"✅ SUCCESS: Thread moved to position {result['queue_position']}")
        else:
            print(f"❌ FAILURE: {reposition_response.status_code} - {reposition_response.text}")
    else:
        print(f"❌ Login failed: {login_response.text}")

except Exception as e:
    print(f"❌ ERROR: {e}")
