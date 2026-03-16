#!/usr/bin/env python3
"""Create interconnected reading order for Ultimate Universe comics.

This script creates linear issue dependencies for the Ultimate Universe
reading order, ensuring comics are read in the correct sequence.

Environment Variables:
    COMIC_PILE_USERNAME: Your username
    COMIC_PILE_PASSWORD: Your password
    COMIC_PILE_API_BASE: API base URL (default: https://app-production-72b9.up.railway.app)

Usage:
    export COMIC_PILE_USERNAME=Josh_Digital_Comics
    export COMIC_PILE_PASSWORD=your_password
    python scripts/create_ultimate_universe_dependencies.py
"""

import os
import re
import sys
from typing import NamedTuple

import requests

API_BASE = os.environ.get(
    "COMIC_PILE_API_BASE", "https://app-production-72b9.up.railway.app"
).rstrip("/")
REQUESTS_TIMEOUT = 30


class ComicIssue(NamedTuple):
    """Parsed comic information."""

    series: str
    issue_number: str
    full_name: str


def parse_comic_entry(entry: str) -> ComicIssue:
    """Parse a comic entry like "Ultimate Spider-Man #1" into components.

    Args:
        entry: Comic entry string

    Returns:
        ComicIssue with series, issue_number, and full_name
    """
    match = re.match(r"(.+?)\s+#([\w.]+)$", entry.strip())
    if match:
        series = match.group(1).strip()
        issue_number = match.group(2)
        return ComicIssue(series=series, issue_number=issue_number, full_name=entry.strip())

    raise ValueError(f"Could not parse entry: {entry}")


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
    """Get all threads and return a mapping of title -> thread info.

    Args:
        token: Authentication token

    Returns:
        Dictionary mapping thread titles to thread info dicts
    """
    response = requests.get(
        f"{API_BASE}/api/threads/",
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQUESTS_TIMEOUT,
    )
    response.raise_for_status()
    threads = response.json()

    return {thread["title"]: thread for thread in threads}


def get_thread_issues(token: str, thread_id: int) -> dict[str, int]:
    """Get all issues for a thread and return issue_number -> issue_id mapping.

    Args:
        token: Authentication token
        thread_id: Thread ID to fetch issues for

    Returns:
        Dictionary mapping issue numbers to issue IDs
    """
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


def find_issue_id(
    token: str, threads: dict[str, dict], comic: ComicIssue
) -> tuple[int, str] | None:
    """Find issue ID for a given comic.

    Args:
        token: Authentication token
        threads: Dictionary of threads
        comic: Parsed comic information

    Returns:
        Tuple of (issue_id, thread_title) if found, None otherwise
    """
    thread = threads.get(comic.series)
    if not thread:
        return None

    thread_id = thread["id"]
    issues = get_thread_issues(token, thread_id)
    issue_id = issues.get(comic.issue_number)

    if issue_id:
        return (issue_id, comic.series)

    return None


def create_dependency(token: str, source_issue_id: int, target_issue_id: int) -> dict | None:
    """Create an issue-level dependency.

    Args:
        token: Authentication token
        source_issue_id: ID of the issue that must be read first
        target_issue_id: ID of the issue that depends on the source

    Returns:
        Dependency dict if created, None if it already exists or failed
    """
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
        return response.json()
    elif response.status_code == 400:
        error = response.json()
        detail = error.get("detail", "")
        if "already exists" in detail.lower():
            return None
        if "circular" in detail.lower():
            print("  ⚠️  Circular dependency detected")
            return None
        print(f"  ❌ Bad Request (400): {error}")
        return None
    else:
        print(f"  ❌ Server error {response.status_code}: {response.text}")
        return None


def main():
    """Main entry point."""
    print("🎯 Creating Ultimate Universe Reading Order Dependencies")
    print("=" * 70)

    username = os.environ.get("COMIC_PILE_USERNAME")
    password = os.environ.get("COMIC_PILE_PASSWORD")

    if not username or not password:
        print("❌ Error: Please set COMIC_PILE_USERNAME and COMIC_PILE_PASSWORD")
        print("   Example: export COMIC_PILE_USERNAME=Josh_Digital_Comics")
        print("            export COMIC_PILE_PASSWORD=your_password")
        return 1

    print(f"\n🔐 Authenticating as {username}...")
    token = login(username, password)
    print("✅ Authenticated successfully")

    print("\n📚 Fetching all threads...")
    threads = get_all_threads(token)
    print(f"✅ Found {len(threads)} threads")

    # Reading order with notes about already-read content
    # - Ultimate Invasion #1-4: COMPLETED (thread status: completed)
    # - Ultimate Universe #1: ALREADY READ (user deleted thread after reading)
    # - Ultimate X-Men #1-6: ALREADY READ (next unread: #7)
    reading_order = [
        # Skip Ultimate Invasion #1-4 (already completed)
        # Skip Ultimate Universe #1 (already read and removed)
        "Ultimate Spider-Man #1",
        "Ultimate Black Panther #1",
        "Ultimate Spider-Man #2",
        # Skip Ultimate X-Men #1-6 (already read)
        "Ultimate Black Panther #2",
        "Ultimate Spider-Man #3",
        "Ultimate X-Men #7",
        "Ultimate Black Panther #3",
        "Ultimate Spider-Man #4",
        "Free Comic Book Day 2024: Ultimate Universe / Spider-Man #1",
        "Ultimate X-Men #8",
        "Ultimate Black Panther #4",
        "Ultimate Spider-Man #5",
        "The Ultimates #1",
        "Ultimate X-Men #9",
        "Ultimate Spider-Man #6",
        "Ultimate Black Panther #5",
        "The Ultimates #2",
        "Ultimate X-Men #10",
        "Ultimate Black Panther #6",
        "Ultimate Spider-Man #7",
        "Ultimate Black Panther #7",
        "The Ultimates #3",
        "Ultimate Spider-Man #8",
        "Ultimate X-Men #11",
        "The Ultimates #4",
        "Ultimate Black Panther #8",
        "Ultimate X-Men #12",
        "Ultimate Spider-Man #9",
        "Ultimate Black Panther #9",
        "The Ultimates #5",
        "Ultimate Spider-Man #10",
        "Ultimate X-Men #13",
        "The Ultimates #6",
        "Ultimate X-Men #14",
        "Ultimate Spider-Man #11",
        "Ultimate Black Panther #10",
        "The Ultimates #7",
        "Ultimate Universe: One Year In #1",
        "Ultimate X-Men #15",
        "Ultimate Spider-Man #12",
        "Ultimate Black Panther #11",
        "The Ultimates #8",
        "Ultimate Black Panther #12",
        "Ultimate Wolverine #1",
        "Ultimate Spider-Man #13",
        "Ultimate X-Men #16",
        "The Ultimates #9",
        "Ultimate Black Panther #13",
        "Ultimate Wolverine #2",
        "Ultimate Spider-Man #14",
        "Ultimate X-Men #17",
        "The Ultimates #10",
        "Ultimate Black Panther #14",
        "Ultimate X-Men #18",
        "Ultimate Spider-Man #15",
        "Ultimate Wolverine #3",
        "Ultimate X-Men #19",
        "The Ultimates #11",
        "Ultimate Wolverine #4",
        "Ultimate Black Panther #15",
        "Ultimate Spider-Man #16",
        "Free Comic Book Day 2025: Amazing Spider-Man / Ultimate Universe #1",
        "Ultimate Wolverine #5",
        "Ultimate Black Panther #16",
        "Ultimate X-Men #20",
        "The Ultimates #12",
        "Ultimate Spider-Man #17",
        "Ultimate Wolverine #6",
        "Ultimate Spider-Man: Incursion #1",
        "Ultimate Black Panther #17",
        "Ultimate X-Men #21",
        "The Ultimates #13",
        "Ultimate Spider-Man #18",
        "Ultimate Wolverine #7",
        "Ultimate Spider-Man: Incursion #2",
        "Ultimate Black Panther #18",
        "Ultimate X-Men #22",
        "Ultimate Spider-Man #19",
        "The Ultimates #14",
        "Ultimate X-Men #23",
        "Ultimate Wolverine #8",
        "The Ultimates #15",
        "Ultimate Spider-Man: Incursion #3",
        "Ultimate Black Panther #19",
        "Ultimate Spider-Man #20",
        "Ultimate X-Men #24",
        "Ultimate Wolverine #9",
        "Ultimate Spider-Man: Incursion #4",
        "Ultimate Black Panther #20",
        "The Ultimates #16",
        "Ultimate Spider-Man #21",
        "Ultimate Hawkeye #1",
        "Ultimate X-Men #25",
        "Ultimate Wolverine #10",
        "Ultimate Black Panther #21",
        "Ultimate Spider-Man #22",
        "Ultimate Spider-Man: Incursion #5",
        "The Ultimates #17",
        "Ultimate X-Men #23",
        "Ultimate Black Panther #22",
        "Ultimate Wolverine #11",
        "The Ultimates #18",
        "Ultimate X-Men #24",
        "Ultimate Universe: Two Years In #1",
        "Ultimate Black Panther #23",
        "Ultimate Wolverine #12",
        "Ultimate Spider-Man #23",
        "Ultimate Endgame #1",
        "The Ultimates #19",
        "Ultimate X-Men #25",
        "Ultimate Wolverine #13",
        "The Ultimates #20",
        "Ultimate Black Panther #24",
        "Ultimate Endgame #2",
        "Ultimate Wolverine #14",
        "Ultimate X-Men #24",
        "Ultimate Spider-Man #24",
        "The Ultimates #21",
        "The Ultimates #22",
        "Ultimate Wolverine #15",
        "Ultimate Endgame #3",
        "Ultimate Wolverine #16",
        "The Ultimates #23",
        "Ultimate Endgame #4",
        "The Ultimates #24",
        "Ultimate Endgame #5",
        "Ultimate Universe: Finale #1",
        "Miles Morales: Spider-Man #1",
        "Ultimate Impact: Reborn #1",
    ]

    print(f"\n📖 Processing {len(reading_order)} comics...")
    print("=" * 70)

    parsed_issues = []
    not_found = []

    for entry in reading_order:
        try:
            comic = parse_comic_entry(entry)
            result = find_issue_id(token, threads, comic)

            if result:
                issue_id, thread_title = result
                parsed_issues.append((comic, issue_id))
                print(f"  ✅ {entry} (issue ID: {issue_id})")
            else:
                not_found.append(entry)
                print(f"  ❌ {entry} - NOT FOUND")
        except ValueError as e:
            not_found.append(entry)
            print(f"  ⚠️  {entry} - {e}")

    if not_found:
        print(f"\n⚠️  Warning: {len(not_found)} comics not found:")
        for entry in not_found:
            print(f"     - {entry}")

    print(f"\n🔗 Creating {len(parsed_issues) - 1} dependencies...")
    print("=" * 70)

    created_count = 0
    skipped_count = 0
    failed_count = 0

    for i in range(len(parsed_issues) - 1):
        source_comic, source_id = parsed_issues[i]
        target_comic, target_id = parsed_issues[i + 1]

        result = create_dependency(token, source_id, target_id)

        if result:
            created_count += 1
            print(f"  ✅ {source_comic.full_name} → {target_comic.full_name}")
        elif result is None:
            skipped_count += 1
            print(f"  ⏭️  {source_comic.full_name} → {target_comic.full_name} (already exists)")
        else:
            failed_count += 1

    print("\n" + "=" * 70)
    print("📊 Summary")
    print("=" * 70)
    print(f"✅ Comics found: {len(parsed_issues)}")
    print(f"❌ Comics not found: {len(not_found)}")
    print(f"🔗 Dependencies created: {created_count}")
    print(f"⏭️  Dependencies already existed: {skipped_count}")
    print(f"❌ Dependencies failed: {failed_count}")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
