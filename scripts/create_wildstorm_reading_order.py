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

import requests

from comic_pile_api import (
    ThreadSpec,
    create_dependency,
    create_thread,
    get_all_threads,
    get_thread_issues,
    login,
    migrate_thread,
)


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

    if "Planetary" in existing_threads:
        planetary_thread = existing_threads["Planetary"]
        next_unread = planetary_thread.get("next_unread_issue_number", "1")
        issues_read = int(next_unread) - 1 if next_unread else 0
        print(f"✅ Planetary exists: next unread is #{next_unread} (read #1-{issues_read})")

    thread_specs = {
        "Stormwatch Vol. 1": ThreadSpec("Stormwatch Vol. 1", 50, []),
        "Stormwatch Vol. 2": ThreadSpec("Stormwatch Vol. 2", 11, []),
        "WildC.A.T.s/Aliens": ThreadSpec("WildC.A.T.s/Aliens", 1, []),
        "Planetary": ThreadSpec("Planetary", 27, list(range(1, 9))),
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
            thread_id = create_thread(token, title, spec.total_issues, format="digital")

        thread_ids[title] = thread_id

        thread_info = existing_threads.get(title, {})
        if thread_info.get("total_issues") is None:
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

    stormwatch_chain = [
        ("Stormwatch Vol. 1", "37"),
        ("Stormwatch Vol. 1", "43"),
        ("Stormwatch Vol. 1", "48"),
        ("Stormwatch Vol. 2", "1"),
        ("Stormwatch Vol. 2", "4"),
        ("WildC.A.T.s/Aliens", "1"),
        ("Stormwatch Vol. 2", "10"),
    ]

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

    planetary_authority_chain = [
        ("Planetary", "1"),
        ("The Authority", "1"),
        ("Planetary", "6"),
        ("The Authority", "5"),
        ("Planetary/The Authority: Ruling the World", "1"),
        ("Planetary", "10"),
        ("The Authority", "9"),
    ]

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

    planetary_late_chain = [
        ("Planetary", "13"),
        ("Planetary", "16"),
        ("Planetary/JLA: Terra Occulta", "1"),
        ("Planetary", "17"),
        ("Planetary/Batman: Night on Earth", "1"),
        ("Planetary", "21"),
        ("Planetary", "24"),
        ("Planetary", "27"),
    ]

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
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
