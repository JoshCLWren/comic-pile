#!/usr/bin/env python3
"""Create Ultimate Universe reading order threads and dependencies from scratch.

This script:
1. Creates all threads with proper issue counts
2. Migrates them to issue tracking
3. Creates dependencies in reading order

Environment Variables:
    COMIC_PILE_USERNAME: Your username
    COMIC_PILE_PASSWORD: Your password
    COMIC_PILE_API_BASE: API base URL (default: https://app-production-72b9.up.railway.app)

Usage:
    export COMIC_PILE_USERNAME=Josh_Digital_Comics
    export COMIC_PILE_PASSWORD=your_password
    python scripts/create_ultimate_universe_from_scratch.py
"""

import os
import sys

from comic_pile_api import (
    ThreadSpecWithLastRead,
    create_dependency,
    create_thread,
    get_thread_issues,
    login,
    migrate_thread,
)


def main() -> int:
    """Main entry point."""
    print("🎯 Creating Ultimate Universe Reading Order")
    print("=" * 70)

    username = os.environ.get("COMIC_PILE_USERNAME")
    password = os.environ.get("COMIC_PILE_PASSWORD")

    if not username or not password:
        print("❌ Error: Please set COMIC_PILE_USERNAME and COMIC_PILE_PASSWORD")
        return 1

    print("\n🔐 Authenticating...")
    token = login(username, password)
    print("✅ Authenticated")

    thread_specs = {
        "Ultimate Spider-Man": ThreadSpecWithLastRead("Ultimate Spider-Man", 24, 0),
        "Ultimate Black Panther": ThreadSpecWithLastRead("Ultimate Black Panther", 24, 0),
        "Ultimate X-Men": ThreadSpecWithLastRead("Ultimate X-Men", 25, 6),
        "The Ultimates": ThreadSpecWithLastRead("The Ultimates", 24, 0),
        "Ultimate Wolverine": ThreadSpecWithLastRead("Ultimate Wolverine", 16, 0),
        "Ultimate Spider-Man: Incursion": ThreadSpecWithLastRead(
            "Ultimate Spider-Man: Incursion", 5, 0
        ),
        "Ultimate Hawkeye": ThreadSpecWithLastRead("Ultimate Hawkeye", 1, 0),
        "Ultimate Endgame": ThreadSpecWithLastRead("Ultimate Endgame", 5, 0),
        "Miles Morales: Spider-Man": ThreadSpecWithLastRead("Miles Morales: Spider-Man", 1, 0),
        "Ultimate Impact: Reborn": ThreadSpecWithLastRead("Ultimate Impact: Reborn", 1, 0),
        "Free Comic Book Day 2024: Ultimate Universe / Spider-Man": ThreadSpecWithLastRead(
            "Free Comic Book Day 2024: Ultimate Universe / Spider-Man", 1, 0
        ),
        "Free Comic Book Day 2025: Amazing Spider-Man / Ultimate Universe": ThreadSpecWithLastRead(
            "Free Comic Book Day 2025: Amazing Spider-Man / Ultimate Universe", 1, 0
        ),
        "Ultimate Universe: One Year In": ThreadSpecWithLastRead(
            "Ultimate Universe: One Year In", 1, 0
        ),
        "Ultimate Universe: Two Years In": ThreadSpecWithLastRead(
            "Ultimate Universe: Two Years In", 1, 0
        ),
        "Ultimate Universe: Finale": ThreadSpecWithLastRead("Ultimate Universe: Finale", 1, 0),
    }

    print(f"\n📚 Creating {len(thread_specs)} threads...")
    print("=" * 70)

    thread_ids = {}
    for title, spec in thread_specs.items():
        print(f"  Creating: {title} ({spec.total_issues} issues)")
        thread_id = create_thread(token, title, spec.total_issues)
        thread_ids[title] = thread_id

    print("\n🔄 Migrating to issue tracking...")
    print("=" * 70)

    for title, spec in thread_specs.items():
        thread_id = thread_ids[title]
        print(f"  Migrating: {title}")
        migrate_thread(token, thread_id, spec.last_issue_read, spec.total_issues)

    print("\n📖 Fetching issue IDs...")
    print("=" * 70)

    thread_issue_ids = {}
    for title in thread_specs.keys():
        thread_id = thread_ids[title]
        issues = get_thread_issues(token, thread_id)
        thread_issue_ids[title] = issues
        print(f"  {title}: {len(issues)} issues")

    reading_order = [
        ("Ultimate Spider-Man", "1"),
        ("Ultimate Black Panther", "1"),
        ("Ultimate Spider-Man", "2"),
        ("Ultimate X-Men", "7"),
        ("Ultimate Black Panther", "2"),
        ("Ultimate Spider-Man", "3"),
        ("Ultimate X-Men", "8"),
        ("Ultimate Black Panther", "3"),
        ("Ultimate Spider-Man", "4"),
        ("Free Comic Book Day 2024: Ultimate Universe / Spider-Man", "1"),
        ("Ultimate X-Men", "9"),
        ("Ultimate Black Panther", "4"),
        ("Ultimate Spider-Man", "5"),
        ("The Ultimates", "1"),
        ("Ultimate X-Men", "10"),
        ("Ultimate Spider-Man", "6"),
        ("Ultimate Black Panther", "5"),
        ("The Ultimates", "2"),
        ("Ultimate X-Men", "11"),
        ("Ultimate Black Panther", "6"),
        ("Ultimate Spider-Man", "7"),
        ("Ultimate Black Panther", "7"),
        ("The Ultimates", "3"),
        ("Ultimate Spider-Man", "8"),
        ("Ultimate X-Men", "12"),
        ("The Ultimates", "4"),
        ("Ultimate Black Panther", "8"),
        ("Ultimate X-Men", "13"),
        ("Ultimate Spider-Man", "9"),
        ("Ultimate Black Panther", "9"),
        ("The Ultimates", "5"),
        ("Ultimate Spider-Man", "10"),
        ("Ultimate X-Men", "14"),
        ("The Ultimates", "6"),
        ("Ultimate X-Men", "15"),
        ("Ultimate Spider-Man", "11"),
        ("Ultimate Black Panther", "10"),
        ("The Ultimates", "7"),
        ("Ultimate Universe: One Year In", "1"),
        ("Ultimate X-Men", "16"),
        ("Ultimate Spider-Man", "12"),
        ("Ultimate Black Panther", "11"),
        ("The Ultimates", "8"),
        ("Ultimate Black Panther", "12"),
        ("Ultimate Wolverine", "1"),
        ("Ultimate Spider-Man", "13"),
        ("Ultimate X-Men", "17"),
        ("The Ultimates", "9"),
        ("Ultimate Black Panther", "13"),
        ("Ultimate Wolverine", "2"),
        ("Ultimate Spider-Man", "14"),
        ("Ultimate X-Men", "18"),
        ("The Ultimates", "10"),
        ("Ultimate Black Panther", "14"),
        ("Ultimate X-Men", "19"),
        ("Ultimate Spider-Man", "15"),
        ("Ultimate Wolverine", "3"),
        ("Ultimate X-Men", "20"),
        ("The Ultimates", "11"),
        ("Ultimate Wolverine", "4"),
        ("Ultimate Black Panther", "15"),
        ("Ultimate Spider-Man", "16"),
        ("Free Comic Book Day 2025: Amazing Spider-Man / Ultimate Universe", "1"),
        ("Ultimate Wolverine", "5"),
        ("Ultimate Black Panther", "16"),
        ("Ultimate X-Men", "21"),
        ("The Ultimates", "12"),
        ("Ultimate Spider-Man", "17"),
        ("Ultimate Wolverine", "6"),
        ("Ultimate Spider-Man: Incursion", "1"),
        ("Ultimate Black Panther", "17"),
        ("Ultimate X-Men", "22"),
        ("The Ultimates", "13"),
        ("Ultimate Spider-Man", "18"),
        ("Ultimate Wolverine", "7"),
        ("Ultimate Spider-Man: Incursion", "2"),
        ("Ultimate Black Panther", "18"),
        ("Ultimate X-Men", "23"),
        ("Ultimate Spider-Man", "19"),
        ("The Ultimates", "14"),
        ("Ultimate X-Men", "24"),
        ("Ultimate Wolverine", "8"),
        ("The Ultimates", "15"),
        ("Ultimate Spider-Man: Incursion", "3"),
        ("Ultimate Black Panther", "19"),
        ("Ultimate Spider-Man", "20"),
        ("Ultimate X-Men", "25"),
        ("Ultimate Wolverine", "9"),
        ("Ultimate Spider-Man: Incursion", "4"),
        ("Ultimate Black Panther", "20"),
        ("The Ultimates", "16"),
        ("Ultimate Spider-Man", "21"),
        ("Ultimate Hawkeye", "1"),
        ("Ultimate Wolverine", "10"),
        ("Ultimate Black Panther", "21"),
        ("Ultimate Spider-Man", "22"),
        ("Ultimate Spider-Man: Incursion", "5"),
        ("The Ultimates", "17"),
        ("Ultimate Black Panther", "22"),
        ("Ultimate Wolverine", "11"),
        ("The Ultimates", "18"),
        ("Ultimate Universe: Two Years In", "1"),
        ("Ultimate Black Panther", "23"),
        ("Ultimate Wolverine", "12"),
        ("Ultimate Spider-Man", "23"),
        ("Ultimate Endgame", "1"),
        ("The Ultimates", "19"),
        ("Ultimate Wolverine", "13"),
        ("The Ultimates", "20"),
        ("Ultimate Black Panther", "24"),
        ("Ultimate Endgame", "2"),
        ("Ultimate Wolverine", "14"),
        ("Ultimate Spider-Man", "24"),
        ("The Ultimates", "21"),
        ("The Ultimates", "22"),
        ("Ultimate Wolverine", "15"),
        ("Ultimate Endgame", "3"),
        ("Ultimate Wolverine", "16"),
        ("The Ultimates", "23"),
        ("Ultimate Endgame", "4"),
        ("The Ultimates", "24"),
        ("Ultimate Endgame", "5"),
        ("Ultimate Universe: Finale", "1"),
        ("Miles Morales: Spider-Man", "1"),
        ("Ultimate Impact: Reborn", "1"),
    ]

    print(f"\n🔗 Creating {len(reading_order) - 1} dependencies...")
    print("=" * 70)

    created_count = 0
    failed_count = 0

    for i in range(len(reading_order) - 1):
        source_title, source_issue = reading_order[i]
        target_title, target_issue = reading_order[i + 1]

        source_issue_id = thread_issue_ids[source_title][source_issue]
        target_issue_id = thread_issue_ids[target_title][target_issue]

        created = create_dependency(token, source_issue_id, target_issue_id)

        if created:
            created_count += 1
            print(f"  ✅ {source_title} #{source_issue} → {target_title} #{target_issue}")
        else:
            failed_count += 1

    print("\n" + "=" * 70)
    print("📊 Summary")
    print("=" * 70)
    print(f"✅ Threads created: {len(thread_specs)}")
    print(f"🔗 Dependencies created: {created_count}")
    print(f"❌ Dependencies failed: {failed_count}")
    print("=" * 70)
    print("\n🎉 Ultimate Universe reading order complete!")
    print("📖 First issue: Ultimate Spider-Man #1 (unlocked, ready to read)")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
