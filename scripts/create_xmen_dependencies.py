#!/usr/bin/env python3
"""Create comic reading order dependencies for X-Men storylines.

Environment Variables:
    COMIC_PILE_USERNAME: Your username
    COMIC_PILE_PASSWORD: Your password

Usage:
    export COMIC_PILE_USERNAME=Josh
    export COMIC_PILE_PASSWORD=your_password
    python scripts/create_xmen_dependencies.py
"""

import os
import requests
from typing import NamedTuple

API_BASE = "https://app-production-72b9.up.railway.app"

# Storyline data with issue IDs (fetched from production database)
STORYLINES = {
    "Hunt for Xavier": [
        (2030, 305, "Uncanny X-Men", "362"),
        (1636, 98, "X-Men", "82"),
        (2031, 305, "Uncanny X-Men", "363"),
        (1637, 98, "X-Men", "83"),
        (2032, 305, "Uncanny X-Men", "364"),
        (1638, 98, "X-Men", "84"),
        (2033, 305, "Uncanny X-Men", "365"),
    ],
    "Magneto War": [
        (1639, 98, "X-Men", "85"),
        (2357, 312, "X-Men: The Magneto War", "1"),
        (2034, 305, "Uncanny X-Men", "366"),
        (1640, 98, "X-Men", "86"),
        (2035, 305, "Uncanny X-Men", "367"),
        (1641, 98, "X-Men", "87"),
    ],
    "The Twelve / Ages of Apocalypse": [
        (2044, 305, "Uncanny X-Men", "376"),
        (1444, 76, "Cable", "75"),
        (1651, 98, "X-Men", "96"),
        (2045, 305, "Uncanny X-Men", "377"),
        (1652, 98, "X-Men", "97"),
        (2046, 305, "Uncanny X-Men", "378"),
        (1653, 98, "X-Men", "98"),
    ],
    "Dream's End": [
        (2056, 305, "Uncanny X-Men", "388"),
        (1663, 98, "X-Men", "108"),
        (2057, 305, "Uncanny X-Men", "389"),
        (1664, 98, "X-Men", "109"),
        (2058, 305, "Uncanny X-Men", "390"),
        (1665, 98, "X-Men", "110"),
    ],
}


class IssueInfo(NamedTuple):
    """Information about a comic issue."""

    issue_id: int
    thread_id: int
    series: str
    number: str


def login(username: str, password: str) -> str:
    """Authenticate and return bearer token."""
    response = requests.post(
        f"{API_BASE}/api/auth/login", json={"username": username, "password": password}
    )
    response.raise_for_status()
    return response.json()["access_token"]


def create_dependency(
    token: str,
    source: IssueInfo,
    target: IssueInfo,
) -> dict | None:
    """Create an issue-level dependency."""
    response = requests.post(
        f"{API_BASE}/api/v1/dependencies/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "source_type": "issue",
            "source_id": source.issue_id,
            "target_type": "issue",
            "target_id": target.issue_id,
        },
    )

    if response.status_code == 201:
        return response.json()
    elif response.status_code == 400:
        error = response.json()
        if "circular" in str(error).lower():
            print(
                f"  ⚠ Skipping circular dependency: {source.series} #{source.number} → {target.series} #{target.number}"
            )
            return None
        print(f"  ❌ Bad Request (400): {error}")
        return None
    else:
        print(f"  ❌ Server error {response.status_code}: {response.text}")
        return None


def create_storyline_dependencies(
    token: str,
    storyline_name: str,
    issues: list[tuple[int, int, str, str]],
) -> int:
    """Create all dependencies for a storyline (linear chain)."""
    print(f"\n📖 {storyline_name}")
    print("=" * 60)

    created_count = 0

    # Create linear chain: issue[0] → issue[1] → issue[2] → ...
    for i in range(len(issues) - 1):
        source = IssueInfo(*issues[i])
        target = IssueInfo(*issues[i + 1])

        result = create_dependency(token, source, target)
        if result:
            created_count += 1
            print(f"  ✅ {source.series} #{source.number} → {target.series} #{target.number}")
            print(f"     (dependency ID: {result['id']})")

    return created_count


def main():
    """Main entry point."""
    print("🎯 Creating X-Men Storyline Dependencies")
    print("=" * 60)

    # Get credentials from environment
    username = os.environ.get("COMIC_PILE_USERNAME")
    password = os.environ.get("COMIC_PILE_PASSWORD")

    if not username or not password:
        print(
            "❌ Error: Please set COMIC_PILE_USERNAME and COMIC_PILE_PASSWORD environment variables"
        )
        print("   Example: export COMIC_PILE_USERNAME=Josh")
        print("            export COMIC_PILE_PASSWORD=your_password")
        return 1

    # Authenticate
    print("\n🔐 Authenticating...")
    token = login(username, password)
    print(f"✅ Authenticated as {username}")

    # Create dependencies for each storyline
    total_created = 0

    for storyline_name, issues in STORYLINES.items():
        count = create_storyline_dependencies(token, storyline_name, issues)
        total_created += count

        if count > 0:
            print(f"\n  ✨ Created {count} dependencies for {storyline_name}")

    # Summary
    print("\n" + "=" * 60)
    print(f"🎉 Total dependencies created: {total_created}")
    print("\n📝 These dependencies ensure you read the issues in the correct")
    print("   storyline order. The dice will respect these dependencies!")
    print("=" * 60)


if __name__ == "__main__":
    main()
