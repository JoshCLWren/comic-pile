#!/usr/bin/env python3
"""Create Absolute Universe reading order threads and dependencies.

This script:
1. Creates all threads with proper issue counts
2. Marks already-read issues as complete
3. Creates dependencies for Earth-0/K.O. chains (strict blocking)
4. Leaves Absolute titles with NO blocking (parallel reads)

Environment Variables:
    COMIC_PILE_USERNAME: Your username
    COMIC_PILE_PASSWORD: Your password

Usage:
    export COMIC_PILE_USERNAME=Josh_Digital_Comics
    export COMIC_PILE_PASSWORD=your_password
    python scripts/create_absolute_universe_reading_order.py
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
        json={"title": title, "format": "Comics", "issues_remaining": issues_count},
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


def mark_issue_read(token: str, thread_id: int, issue_number: str) -> bool:
    """Mark an issue as read. Returns True if successful, False otherwise."""
    # Get all issues to find the issue ID
    page_token = ""
    issue_id = None

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
                issue_id = issue["id"]
                # Check if already read
                if issue.get("status") == "read":
                    return False
                break

        if issue_id:
            break

        page_token = data.get("next_page_token")
        if not page_token:
            break

    if not issue_id:
        print(f"  ⚠️  Could not find issue #{issue_number}")
        return False

    # Mark as read
    try:
        response = requests.post(
            f"{API_BASE}/api/v1/issues/{issue_id}:markRead",
            headers={"Authorization": f"Bearer {token}"},
            timeout=REQUESTS_TIMEOUT,
        )
        response.raise_for_status()
        return True
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 409:
            return False
        raise


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
    print("🎯 Creating Absolute Universe Reading Order")
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

    # Thread specifications: title -> (total_issues, issues_already_read)
    thread_specs = {
        # Earth-0 chain
        "Dark Nights: Death Metal": ThreadSpec("Dark Nights: Death Metal", 7, []),
        "Superman": ThreadSpec("Superman", 35, []),
        "The Flash": ThreadSpec("The Flash", 30, []),
        "Justice League: Dark Tomorrow Special": ThreadSpec(
            "Justice League: Dark Tomorrow Special", 1, []
        ),
        "Justice League Unlimited": ThreadSpec("Justice League Unlimited", 11, []),
        "Justice League: The Omega Act Special": ThreadSpec(
            "Justice League: The Omega Act Special", 1, []
        ),
        "Summer of Superman Special": ThreadSpec("Summer of Superman Special", 1, []),
        "DC K.O.": ThreadSpec("DC K.O.", 5, []),
        # Absolute titles
        "Absolute Batman": ThreadSpec("Absolute Batman", 20, []),
        "Absolute Wonder Woman": ThreadSpec("Absolute Wonder Woman", 20, [1, 2]),
        "Absolute Superman": ThreadSpec("Absolute Superman", 18, []),
        "Absolute Flash": ThreadSpec("Absolute Flash", 15, []),
        "Absolute Martian Manhunter": ThreadSpec("Absolute Martian Manhunter", 12, [1]),
        "Absolute Green Lantern": ThreadSpec("Absolute Green Lantern", 14, []),
        "Absolute Green Arrow": ThreadSpec("Absolute Green Arrow", 1, []),
        "Absolute Catwoman": ThreadSpec("Absolute Catwoman", 1, []),
        # Specials
        "Absolute Specials": ThreadSpec(
            "Absolute Specials",
            4,
            [],
        ),  # Will contain: Evil #1, Batman 2025 Annual #1, Ark M Special #1, Wonder Woman 2026 Annual #1
        "Free Comic Book Day 2025: DC All In Special Edition": ThreadSpec(
            "Free Comic Book Day 2025: DC All In Special Edition", 1, []
        ),
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
        if thread_info.get("total_issues") is not None:
            print(f"  ✅ Already migrated: {title}")
        else:
            # Migrate to issue tracking
            try:
                migrate_thread(token, thread_id, len(spec.issues_to_mark_read), spec.total_issues)
            except requests.HTTPError as e:
                if e.response is not None and "already uses issue tracking" in e.response.text:
                    pass
                else:
                    print(f"  ⚠️  Migration issue for {title}: {e}")

    print("\n✅ Marking already-read issues...")
    print("=" * 70)

    for title, spec in thread_specs.items():
        if spec.issues_to_mark_read:
            thread_id = thread_ids[title]
            for issue_num in spec.issues_to_mark_read:
                if mark_issue_read(token, thread_id, str(issue_num)):
                    print(f"  ✅ {title} #{issue_num} marked read")

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

    # Earth-0 chain (STRICT ORDER)
    earth_0_chain = [
        ("Dark Nights: Death Metal", "7"),
        ("Superman", "23"),
        ("Superman", "26"),
        ("Summer of Superman Special", "1"),
        ("Superman", "27"),
        ("Free Comic Book Day 2025: DC All In Special Edition", "1"),
        ("Superman", "28"),
        ("Justice League: Dark Tomorrow Special", "1"),
        ("Superman", "29"),
        ("Justice League Unlimited", "10"),
        ("Superman", "30"),
        ("Justice League Unlimited", "11"),
        ("Justice League: The Omega Act Special", "1"),
        ("DC K.O.", "1"),
    ]

    # K.O. tie-ins (parallel after K.O. #1)
    ko_tie_ins = [
        ("Superman", "31"),
        ("Superman", "32"),
        ("Superman", "34"),
        ("Superman", "35"),
        ("The Flash", "26"),
        ("The Flash", "27"),
        ("The Flash", "29"),
        ("The Flash", "30"),
    ]

    # K.O. chain continuation
    ko_continuation = [
        ("DC K.O.", "3"),
        ("DC K.O.", "4"),
        ("DC K.O.", "5"),
    ]

    created_count = 0

    # Create Earth-0 chain dependencies
    for i in range(len(earth_0_chain) - 1):
        source_title, source_issue = earth_0_chain[i]
        target_title, target_issue = earth_0_chain[i + 1]

        source_issue_id = thread_issue_ids[source_title][source_issue]
        target_issue_id = thread_issue_ids[target_title][target_issue]

        if create_dependency(token, source_issue_id, target_issue_id):
            created_count += 1
            print(f"  ✅ {source_title} #{source_issue} → {target_title} #{target_issue}")

    # All K.O. tie-ins depend on K.O. #1
    ko_1_id = thread_issue_ids["DC K.O."]["1"]
    for title, issue in ko_tie_ins:
        issue_id = thread_issue_ids[title][issue]
        if create_dependency(token, ko_1_id, issue_id):
            created_count += 1
            print(f"  ✅ DC K.O. #1 → {title} #{issue}")

    # All K.O. tie-ins must be read before K.O. #3
    ko_3_id = thread_issue_ids["DC K.O."]["3"]
    for title, issue in ko_tie_ins:
        issue_id = thread_issue_ids[title][issue]
        if create_dependency(token, issue_id, ko_3_id):
            created_count += 1
            print(f"  ✅ {title} #{issue} → DC K.O. #3")

    # Create K.O. continuation dependencies
    for i in range(len(ko_continuation) - 1):
        source_title, source_issue = ko_continuation[i]
        target_title, target_issue = ko_continuation[i + 1]

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
    print("  🟣 Absolute titles: NO blocking (read in any order)")
    print("  🟠 Earth-0 chain: STRICT blocking (must read in order)")
    print("  🟡 K.O. tie-ins: Parallel between K.O. #1 and #3")
    print("=" * 70)
    print("\n🎉 Absolute Universe reading order complete!")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
