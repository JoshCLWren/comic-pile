#!/usr/bin/env python3
# DEPRECATED: This script is superseded by the issue management API.
# See: POST /api/v1/threads/{id}/issues with insert_after_issue_id and
# POST /api/v1/dependencies/. Retained for reference only. Do not use for new operations.
"""Add annual issues to main X-Men threads and create reading order dependencies.

Environment Variables:
    COMIC_PILE_USERNAME: Your username
    COMIC_PILE_PASSWORD: Your password

Usage:
    export COMIC_PILE_USERNAME=Josh
    export COMIC_PILE_PASSWORD=your_password
    python scripts/add_xmen_annuals.py
"""

import os
import requests

API_BASE = "https://app-production-72b9.up.railway.app"

# Annuals to add: {thread_id: [(annual_name, after_issue_number)]}
ANNUALS_TO_ADD = {
    98: [  # X-Men
        ("X-Men/Dr. Doom Annual 1998", "79"),
        ("X-Men Annual '99", "91"),
        ("X-Men Annual 2001", "113"),
    ],
    305: [  # Uncanny X-Men
        ("Uncanny X-Men Annual 1999", "377"),
        ("Uncanny X-Men Annual 2001", "400"),
    ],
    76: [  # Cable
        ("Cable Annual '99", "59"),
    ],
    102: [  # X-Force
        ("X-Force/Champions Annual 1998", "85"),
        ("X-Force Annual 1999", "95"),
    ],
}


def login(username: str, password: str) -> str:
    """Authenticate and return bearer token."""
    response = requests.post(
        f"{API_BASE}/api/auth/login", json={"username": username, "password": password}
    )
    response.raise_for_status()
    return response.json()["access_token"]


def get_issue_id(token: str, thread_id: int, issue_number: str) -> int | None:
    """Get issue ID for a given thread and issue number."""
    page_token = ""
    while True:
        url = f"{API_BASE}/api/v1/threads/{thread_id}/issues"
        params = {}
        if page_token:
            params["page_token"] = page_token

        response = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
        response.raise_for_status()
        data = response.json()

        for issue in data.get("issues", []):
            if issue["issue_number"] == issue_number:
                return issue["id"]

        page_token = data.get("next_page_token")
        if not page_token:
            break

    return None


def create_annual_issue(token: str, thread_id: int, annual_name: str) -> int | None:
    """Create an annual issue in the given thread."""
    response = requests.post(
        f"{API_BASE}/api/v1/threads/{thread_id}/issues",
        headers={"Authorization": f"Bearer {token}"},
        json={"issue_range": annual_name},
    )

    if response.status_code != 201:
        print(f"  ❌ Failed to create {annual_name}: {response.json()}")
        return None

    data = response.json()
    if data.get("issues"):
        return data["issues"][0]["id"]

    return None


def create_dependency(
    token: str,
    source_issue_id: int,
    target_issue_id: int,
) -> bool:
    """Create an issue-level dependency."""
    response = requests.post(
        f"{API_BASE}/api/v1/dependencies/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "source_type": "issue",
            "source_id": source_issue_id,
            "target_type": "issue",
            "target_id": target_issue_id,
        },
    )

    if response.status_code == 201:
        return True
    elif "already exists" in response.json().get("detail", "").lower():
        print("  ⚠ Dependency already exists")
        return True
    else:
        print(f"  ❌ Failed to create dependency: {response.json()}")
        return False


def main():
    """Main entry point."""
    print("📅 Adding X-Men Annuals to Main Threads")
    print("=" * 70)

    # Get credentials
    username = os.environ.get("COMIC_PILE_USERNAME")
    password = os.environ.get("COMIC_PILE_PASSWORD")

    if not username or not password:
        print("❌ Error: Please set COMIC_PILE_USERNAME and COMIC_PILE_PASSWORD")
        return 1

    # Authenticate
    print("\n🔐 Authenticating...")
    token = login(username, password)
    print(f"✅ Authenticated as {username}")

    total_created = 0
    total_dependencies = 0

    # Process each thread
    for thread_id, annuals in ANNUALS_TO_ADD.items():
        # Get thread name
        response = requests.get(
            f"{API_BASE}/api/threads/", headers={"Authorization": f"Bearer {token}"}
        )
        threads = response.json()
        thread_name = next(
            (t["title"] for t in threads if t["id"] == thread_id), f"Thread {thread_id}"
        )

        print(f"\n{'=' * 70}")
        print(f"📖 {thread_name}")
        print("=" * 70)

        for annual_name, after_issue in annuals:
            print(f"\n  📅 {annual_name} (after #{after_issue})")

            # Create the annual issue
            annual_id = create_annual_issue(token, thread_id, annual_name)
            if not annual_id:
                continue

            print(f"     ✅ Created as issue ID {annual_id}")

            # Get the "after" issue ID
            after_issue_id = get_issue_id(token, thread_id, after_issue)
            if not after_issue_id:
                print(f"     ❌ Could not find issue #{after_issue}")
                continue

            # Create dependency: after_issue → annual
            print(f"     🔗 Creating dependency: #{after_issue} → {annual_name}")
            if not create_dependency(token, after_issue_id, annual_id):
                continue

            total_dependencies += 1
            print("     ✅ Dependency created")

            # Find the next issue after the "after" issue
            # We need to find what comes after #{after_issue} numerically
            try:
                after_num = int(after_issue)
                next_issue_num = str(after_num + 1)

                print(f"     🔗 Looking for issue #{next_issue_num}...")
                next_issue_id = get_issue_id(token, thread_id, next_issue_num)

                if next_issue_id:
                    # Create dependency: annual → next_issue
                    print(f"     🔗 Creating dependency: {annual_name} → #{next_issue_num}")
                    if create_dependency(token, annual_id, next_issue_id):
                        total_dependencies += 1
                        print("     ✅ Dependency created")
                        total_created += 1
                else:
                    print(f"     ⚠ Issue #{next_issue_num} not found, skipping")
            except ValueError:
                print("     ⚠ Could not determine next issue (non-numeric issue number)")

            total_created += 1

    # Summary
    print(f"\n{'=' * 70}")
    print("📊 Summary")
    print("=" * 70)
    print(f"✅ Annuals created and linked: {total_created}")
    print(f"🔗 Dependencies created: {total_dependencies}")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    exit(main())
