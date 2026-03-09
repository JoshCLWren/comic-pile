#!/usr/bin/env python3
# DEPRECATED: This script is superseded by the dependency API.
# See: POST /api/v1/dependencies/.
# Retained for reference only. Do not use for new operations.
"""Complete annual dependency chains by linking annuals to next issues.

This script creates the second half of the dependency chains:
- annual → next_issue

complementing the existing:
- previous_issue → annual

Usage:
    export COMIC_PILE_API_BASE=http://localhost:8000
    export COMIC_PILE_USERNAME=Josh
    export COMIC_PILE_PASSWORD=your_password
    python scripts/complete_annual_dependencies.py
"""

import os
import requests

API_BASE = os.environ.get("COMIC_PILE_API_BASE", "").rstrip("/")
REQUESTS_TIMEOUT = 10

if not API_BASE:
    raise RuntimeError("Set COMIC_PILE_API_BASE before running scripts/complete_annual_dependencies.py")

# Annuals to link: {thread_id: [(annual_name, after_issue_number)]}
ANNUALS = {
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
        f"{API_BASE}/api/auth/login",
        json={"username": username, "password": password},
        timeout=REQUESTS_TIMEOUT,
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

        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=REQUESTS_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

        for issue in data.get("issues", []):
            if issue["issue_number"] == issue_number:
                return issue["id"]

        page_token = data.get("next_page_token")
        if not page_token:
            break

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
        timeout=REQUESTS_TIMEOUT,
    )

    if response.status_code == 201:
        return True
    elif "already exists" in response.json().get("detail", "").lower():
        return True
    else:
        return False


def main():
    """Main entry point."""
    print("🔗 Completing Annual Dependency Chains")
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

    # Process each thread
    for thread_id, annuals in ANNUALS.items():
        # Get thread name
        response = requests.get(
            f"{API_BASE}/api/threads/",
            headers={"Authorization": f"Bearer {token}"},
            timeout=REQUESTS_TIMEOUT,
        )
        threads = response.json()
        thread_name = next(
            (t["title"] for t in threads if t["id"] == thread_id), f"Thread {thread_id}"
        )

        print(f"\n{'=' * 70}")
        print(f"📖 {thread_name}")
        print("=" * 70)

        for annual_name, after_issue in annuals:
            print(f"\n  📅 {annual_name}")

            # Get the annual issue ID
            annual_id = get_issue_id(token, thread_id, annual_name)
            if not annual_id:
                print("     ❌ Could not find annual")
                continue

            # Find the next issue
            try:
                after_num = int(after_issue)
                next_issue_num = str(after_num + 1)

                print(f"     🔗 Linking to issue #{next_issue_num}...")
                next_issue_id = get_issue_id(token, thread_id, next_issue_num)

                if next_issue_id:
                    # Create dependency: annual → next_issue
                    if create_dependency(token, annual_id, next_issue_id):
                        print(f"     ✅ Created: {annual_name} → #{next_issue_num}")
                        total_created += 1
                    else:
                        print("     ❌ Failed to create dependency")
                else:
                    print(f"     ⚠ Issue #{next_issue_num} not found")
            except ValueError:
                print("     ⚠ Could not determine next issue")

    # Summary
    print(f"\n{'=' * 70}")
    print("📊 Summary")
    print("=" * 70)
    print(f"✅ Dependencies created: {total_created}")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    exit(main())
