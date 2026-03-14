#!/usr/bin/env python3
"""Create Warren Ellis Wildstorm reading order with dependencies.

This script creates the proper reading order for:
- Stormwatch (1996-1998)
- Planetary and The Authority interleaved (1999-2000)
- Planetary mid-run and DC crossovers (2003-2009)

Environment Variables:
    COMIC_PILE_USERNAME: Your username
    COMIC_PILE_PASSWORD: Your password

Usage:
    export COMIC_PILE_USERNAME=Josh_Digital_Comics
    export COMIC_PILE_PASSWORD=your_password
    python scripts/create_wildstorm_reading_order.py
"""

import os
import sys
from typing import NamedTuple

import requests

API_BASE = "https://app-production-72b9.up.railway.app"
REQUESTS_TIMEOUT = 30


class ThreadSpec(NamedTuple):
    """Specification for creating/updating a thread."""

    title: str
    total_issues: int
    issues_to_mark_read: list[int]


def login(username: str, password: str) -> str:
    """Authenticate and return bearer token."""
    response = requests.post(
        f"{API_BASE}/api/auth/login",
        json={"username": username, "password": password},
        timeout=REQUESTS_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def get_all_threads(token: str) -> dict[str, dict]:
    """Get all threads and return title -> thread mapping."""
    response = requests.get(
        f"{API_BASE}/api/threads/",
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQUESTS_TIMEOUT,
    )
    response.raise_for_status()
    return {thread["title"]: thread for thread in response.json()}


def create_thread(token: str, title: str, issues_count: int) -> int:
    """Create a thread and return its ID."""
    response = requests.post(
        f"{API_BASE}/api/threads/",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": title, "format": "digital", "issues_remaining": issues_count},
        timeout=REQUESTS_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["id"]


def migrate_thread(token: str, thread_id: int, last_issue_read: int, total_issues: int) -> None:
    """Migrate a thread to issue tracking."""
    response = requests.post(
        f"{API_BASE}/api/threads/{thread_id}:migrateToIssues",
        headers={"Authorization": f"Bearer {token}"},
        json={"last_issue_read": last_issue_read, "total_issues": total_issues},
        timeout=REQUESTS_TIMEOUT,
    )
    response.raise_for_status()


def get_thread_issues(token: str, thread_id: int) -> dict[str, int]:
    """Get issue_number -> issue_id mapping."""
    page_token = ""
    issues = {}

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
            issues[issue["issue_number"]] = issue["id"]

        page_token = data.get("next_page_token")
        if not page_token:
            break

    return issues


def create_dependency(token: str, source_issue_id: int, target_issue_id: int) -> bool:
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
    elif response.status_code == 400:
        error = response.json()
        detail = error.get("detail", "")
        if "already exists" in detail.lower() or "circular" in detail.lower():
            return False
        print(f"  ❌ Bad Request: {error}")
        return False
    else:
        print(f"  ❌ Server error {response.status_code}: {response.text}")
        return False


def main() -> int:
    """Main entry point."""
    print("🎯 Creating Warren Ellis Wildstorm Reading Order")
    print("=" * 70)

    username = os.environ.get("COMIC_PILE_USERNAME")
    password = os.environ.get("COMIC_PILE_PASSWORD")

    if not username or not password:
        print("❌ Error: Please set COMIC_PILE_USERNAME and COMIC_PILE_PASSWORD")
        return 1

    print("\n🔐 Authenticating...")
    token = login(username, password)
    print("✅ Authenticated")

    print("\n📚 Checking existing threads...")
    existing_threads = get_all_threads(token)

    # Check if Planetary exists and what's been read
    if "Planetary" in existing_threads:
        planetary_thread = existing_threads["Planetary"]
        next_unread = planetary_thread.get("next_unread_issue_number", "1")
        issues_read = int(next_unread) - 1 if next_unread else 0
        print(f"✅ Planetary exists: next unread is #{next_unread} (read #1-{issues_read})")

    # Thread specifications
    thread_specs = {
        "Stormwatch Vol. 1": ThreadSpec("Stormwatch Vol. 1", 50, []),  # Issues #37-50
        "Stormwatch Vol. 2": ThreadSpec("Stormwatch Vol. 2", 11, []),  # Issues #1-11
        "WildC.A.T.s/Aliens": ThreadSpec("WildC.A.T.s/Aliens", 1, []),
        "Planetary": ThreadSpec("Planetary", 27, list(range(1, 9))),  # Already read #1-8
        "The Authority": ThreadSpec("The Authority", 12, []),
        "Planetary/The Authority: Ruling the World": ThreadSpec(
            "Planetary/The Authority: Ruling the World", 1, []
        ),
        "Jenny Sparks: The Secret History of the Authority": ThreadSpec(
            "Jenny Sparks: The Secret History of the Authority", 5, []
        ),
        "Planetary/JLA: Terra Occulta": ThreadSpec("Planetary/JLA: Terra Occulta", 1, []),
        "Planetary/Batman: Night on Earth": ThreadSpec("Planetary/Batman: Night on Earth", 1, []),
    }

    print("\n📝 Creating/migrating threads...")
    print("=" * 70)

    thread_ids = {}
    for title, spec in thread_specs.items():
        if title in existing_threads:
            thread_id = existing_threads[title]["id"]
            print(f"  ✅ Using existing: {title}")
        else:
            print(f"  Creating: {title}")
            thread_id = create_thread(token, title, spec.total_issues)

        thread_ids[title] = thread_id

        # Check if already migrated
        thread_info = existing_threads.get(title, {})
        if thread_info.get("total_issues") is None:
            # Migrate to issue tracking
            try:
                migrate_thread(token, thread_id, len(spec.issues_to_mark_read), spec.total_issues)
            except requests.HTTPError as e:
                if e.response is not None and "already uses issue tracking" in e.response.text:
                    pass
                else:
                    print(f"  ⚠️  Migration issue for {title}: {e}")

    print("\n📖 Fetching issue IDs...")
    print("=" * 70)

    thread_issue_ids = {}
    for title in thread_specs.keys():
        thread_id = thread_ids[title]
        issues = get_thread_issues(token, thread_id)
        thread_issue_ids[title] = issues
        print(f"  {title}: {len(issues)} issues")

    print("\n🔗 Creating dependencies...")
    print("=" * 70)

    created_count = 0

    # Stormwatch chain
    stormwatch_chain = [
        ("Stormwatch Vol. 1", "37"),
        ("Stormwatch Vol. 1", "43"),
        ("Stormwatch Vol. 1", "48"),
        ("Stormwatch Vol. 2", "1"),
        ("Stormwatch Vol. 2", "4"),
        ("WildC.A.T.s/Aliens", "1"),  # HARD BLOCK
        ("Stormwatch Vol. 2", "10"),
    ]

    # Create Stormwatch dependencies
    for i in range(len(stormwatch_chain) - 1):
        source_title, source_issue = stormwatch_chain[i]
        target_title, target_issue = stormwatch_chain[i + 1]

        if (
            source_issue in thread_issue_ids[source_title]
            and target_issue in thread_issue_ids[target_title]
        ):
            source_issue_id = thread_issue_ids[source_title][source_issue]
            target_issue_id = thread_issue_ids[target_title][target_issue]

            if create_dependency(token, source_issue_id, target_issue_id):
                created_count += 1
                print(f"  ✅ {source_title} #{source_issue} → {target_title} #{target_issue}")

    # Planetary/Authority interleaved
    planetary_authority_chain = [
        ("Planetary", "1"),
        ("The Authority", "1"),
        ("Planetary", "6"),
        ("The Authority", "5"),  # HARD BLOCK before Ruling the World
        ("Planetary/The Authority: Ruling the World", "1"),
        ("Planetary", "10"),  # HARD BLOCK - Fourth Man reveal
        ("The Authority", "9"),
    ]

    # Create Planetary/Authority dependencies
    for i in range(len(planetary_authority_chain) - 1):
        source_title, source_issue = planetary_authority_chain[i]
        target_title, target_issue = planetary_authority_chain[i + 1]

        if (
            source_issue in thread_issue_ids[source_title]
            and target_issue in thread_issue_ids[target_title]
        ):
            source_issue_id = thread_issue_ids[source_title][source_issue]
            target_issue_id = thread_issue_ids[target_title][target_issue]

            if create_dependency(token, source_issue_id, target_issue_id):
                created_count += 1
                print(f"  ✅ {source_title} #{source_issue} → {target_title} #{target_issue}")

    # Planetary mid-run and crossovers
    planetary_late_chain = [
        ("Planetary", "13"),
        ("Planetary", "16"),
        ("Planetary/JLA: Terra Occulta", "1"),  # Optional, self-contained
        ("Planetary", "17"),
        ("Planetary/Batman: Night on Earth", "1"),  # Optional, self-contained
        ("Planetary", "21"),
        ("Planetary", "24"),  # HARD BLOCK - endgame
        ("Planetary", "27"),
    ]

    # Create late Planetary dependencies
    for i in range(len(planetary_late_chain) - 1):
        source_title, source_issue = planetary_late_chain[i]
        target_title, target_issue = planetary_late_chain[i + 1]

        if (
            source_issue in thread_issue_ids[source_title]
            and target_issue in thread_issue_ids[target_title]
        ):
            source_issue_id = thread_issue_ids[source_title][source_issue]
            target_issue_id = thread_issue_ids[target_title][target_issue]

            if create_dependency(token, source_issue_id, target_issue_id):
                created_count += 1
                print(f"  ✅ {source_title} #{source_issue} → {target_title} #{target_issue}")

    print("\n" + "=" * 70)
    print("📊 Summary")
    print("=" * 70)
    print(f"✅ Dependencies created: {created_count}")
    print("\n📖 Reading structure:")
    print("  🔵 Stormwatch chain: STRICT ORDER (with WildC.A.T.s/Aliens block)")
    print("  🟢 Planetary/Authority: Interleaved with hard blocks")
    print("  🟡 Planetary late: Crossovers + endgame (#24-26)")
    print("=" * 70)
    print("\n🎉 Warren Ellis Wildstorm reading order complete!")
    print("📖 Next issue: Planetary #9 (you've read #1-8)")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
