#!/usr/bin/env python3
"""Check existing dependencies and identify what's missing for X-Men storylines."""

import os
import requests

API_BASE = "https://app-production-72b9.up.railway.app"

# Desired dependency chains for storylines
STORYLINES = {
    "Hunt for Xavier": [
        ("Uncanny X-Men", "362", "X-Men", "82"),
        ("X-Men", "82", "Uncanny X-Men", "363"),
        ("Uncanny X-Men", "363", "X-Men", "83"),
        ("X-Men", "83", "Uncanny X-Men", "364"),
        ("Uncanny X-Men", "364", "X-Men", "84"),
        ("X-Men", "84", "Uncanny X-Men", "365"),
    ],
    "Magneto War": [
        ("X-Men", "85", "X-Men: The Magneto War", "1"),
        ("X-Men: The Magneto War", "1", "Uncanny X-Men", "366"),
        ("Uncanny X-Men", "366", "X-Men", "86"),
        ("X-Men", "86", "Uncanny X-Men", "367"),
        ("Uncanny X-Men", "367", "X-Men", "87"),
    ],
    "The Twelve / Ages of Apocalypse": [
        ("Uncanny X-Men", "376", "Cable", "75"),
        ("Cable", "75", "X-Men", "96"),
        ("X-Men", "96", "Uncanny X-Men", "377"),
        ("Uncanny X-Men", "377", "X-Men", "97"),
        ("X-Men", "97", "Uncanny X-Men", "378"),
        ("Uncanny X-Men", "378", "X-Men", "98"),
    ],
    "Dream's End": [
        ("Uncanny X-Men", "388", "X-Men", "108"),
        ("X-Men", "108", "Uncanny X-Men", "389"),
        ("Uncanny X-Men", "389", "X-Men", "109"),
        ("X-Men", "109", "Uncanny X-Men", "390"),
        ("Uncanny X-Men", "390", "X-Men", "110"),
    ],
}


def login(username: str, password: str) -> str:
    """Authenticate and return bearer token."""
    response = requests.post(
        f"{API_BASE}/api/auth/login", json={"username": username, "password": password}
    )
    response.raise_for_status()
    return response.json()["access_token"]


def get_thread_id(title: str, threads: list) -> int | None:
    """Find thread ID by title."""
    for thread in threads:
        if thread["title"].lower() == title.lower():
            return thread["id"]
    return None


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


def check_dependency_exists(
    token: str,
    source_thread_id: int,
    target_thread_id: int,
) -> dict:
    """Check if any dependencies exist between two threads."""
    response = requests.get(
        f"{API_BASE}/api/v1/threads/{source_thread_id}/dependencies",
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    data = response.json()

    # Return all blocking dependencies
    return data.get("blocking", [])


def main():
    """Main entry point."""
    print("🔍 Checking X-Men Storyline Dependencies")
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

    # Get all threads
    response = requests.get(
        f"{API_BASE}/api/threads/", headers={"Authorization": f"Bearer {token}"}
    )
    response.raise_for_status()
    threads = response.json()

    print(f"\n📚 Loaded {len(threads)} threads")

    # Check each storyline
    total_missing = 0
    total_exists = 0

    for storyline_name, dependencies in STORYLINES.items():
        print(f"\n{'=' * 70}")
        print(f"📖 {storyline_name}")
        print("=" * 70)

        for dep in dependencies:
            source_series, source_num, target_series, target_num = dep

            # Find thread IDs
            source_thread_id = get_thread_id(source_series, threads)
            target_thread_id = get_thread_id(target_series, threads)

            if not source_thread_id or not target_thread_id:
                print(f"❌ {source_series} #{source_num} → {target_series} #{target_num}")
                print("   Could not find thread IDs")
                continue

            # Get issue IDs
            source_issue_id = get_issue_id(token, source_thread_id, source_num)
            target_issue_id = get_issue_id(token, target_thread_id, target_num)

            if not source_issue_id or not target_issue_id:
                print(f"❌ {source_series} #{source_num} → {target_series} #{target_num}")
                print("   Could not find issue IDs")
                continue

            # Check if dependency exists
            existing_deps = check_dependency_exists(token, source_thread_id, target_thread_id)

            # Look for this specific dependency
            exists = False
            for existing_dep in existing_deps:
                if (
                    existing_dep.get("source_issue_id") == source_issue_id
                    and existing_dep.get("target_issue_id") == target_issue_id
                ):
                    exists = True
                    break

            if exists:
                print(f"✅ {source_series} #{source_num} → {target_series} #{target_num}")
                total_exists += 1
            else:
                print(f"❌ {source_series} #{source_num} → {target_series} #{target_num} (MISSING)")
                total_missing += 1

    # Summary
    print(f"\n{'=' * 70}")
    print("📊 Summary")
    print("=" * 70)
    print(f"✅ Existing dependencies: {total_exists}")
    print(f"❌ Missing dependencies:  {total_missing}")
    print(f"📝 Total needed:          {total_exists + total_missing}")

    if total_missing > 0:
        print(f"\n⚠️  {total_missing} dependencies are missing from your storylines!")
        print("   These should be created for proper reading order.")

    return 0


if __name__ == "__main__":
    exit(main())
