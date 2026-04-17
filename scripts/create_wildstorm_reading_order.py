#!/usr/bin/env python3
"""Create Warren Ellis Wildstorm reading order with dependencies.

This script creates the proper reading order for:
- Stormwatch (1996-1998)
- Planetary and The Authority interleaved (1999-2000)
- Planetary mid-run and DC crossovers (2003-2009)

Chain specifications are loaded from scripts/wildstorm_reading_order.yaml.

Environment Variables:
    COMIC_PILE_USERNAME: Your username
    COMIC_PILE_PASSWORD: Your password

Usage:
    export COMIC_PILE_USERNAME=Josh_Digital_Comics
    export COMIC_PILE_PASSWORD=your_password
    python scripts/create_wildstorm_reading_order.py              # Create all deps
    python scripts/create_wildstorm_reading_order.py --verify     # Verify only
    python scripts/create_wildstorm_reading_order.py --fix        # Create only missing deps
"""

import argparse
import os
import sys

import requests

from comic_pile_api import (
    ThreadSpec,
    VerificationResult,
    create_dependency,
    create_thread,
    get_all_threads,
    get_thread_issues,
    login,
    migrate_thread,
    verify_reading_order,
)
from wildstorm_chains import load_chains_as_list, load_chains


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Command-line argument strings.

    Returns:
        Parsed namespace with verify and fix boolean flags.
    """
    parser = argparse.ArgumentParser(
        description="Manage Warren Ellis Wildstorm reading order dependencies",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--verify",
        action="store_true",
        help="Verify dependencies only; do not create or modify anything",
    )
    group.add_argument(
        "--fix",
        action="store_true",
        help="Verify first, then create only the missing dependencies",
    )
    return parser.parse_args(argv)


def _authenticate() -> str:
    """Authenticate with Comic Pile API using environment credentials.

    Returns:
        Bearer token string.

    Raises:
        SystemExit: If credentials are not set.
    """
    username = os.environ.get("COMIC_PILE_USERNAME")
    password = os.environ.get("COMIC_PILE_PASSWORD")

    if not username or not password:
        print("Error: Please set COMIC_PILE_USERNAME and COMIC_PILE_PASSWORD")
        raise SystemExit(1)

    print("\nAuthenticating...")
    token = login(username, password)
    print("Authenticated")
    return token


def _print_verification_report(result: VerificationResult) -> None:
    """Print a human-readable verification report.

    Args:
        result: Verification result with present, missing, unexpected, not_found lists.
    """
    present = result["present"]
    missing = result["missing"]
    unexpected = result["unexpected"]
    not_found = result["not_found"]

    if present:
        print(f"  ✅ Present ({len(present)}):")
        for edge in present:
            print(
                f"    {edge.source_title} #{edge.source_issue} -> {edge.target_title} #{edge.target_issue}"
            )

    if missing:
        print(f"  ❌ Missing ({len(missing)}):")
        for edge in missing:
            print(
                f"    {edge.source_title} #{edge.source_issue} -> {edge.target_title} #{edge.target_issue}"
            )

    if unexpected:
        print(f"  ⚠️ Unexpected ({len(unexpected)}):")
        for edge in unexpected:
            print(
                f"    {edge.source_title} #{edge.source_issue} -> {edge.target_title} #{edge.target_issue}"
            )

    if not_found:
        print(f"  🔍 Not found in DB ({len(not_found)}):")
        for edge in not_found:
            print(
                f"    {edge.source_title} #{edge.source_issue} -> {edge.target_title} #{edge.target_issue}"
            )

    total = len(present) + len(missing) + len(unexpected) + len(not_found)
    print(
        f"  Total: {total} edges | {len(present)} present | {len(missing)} missing"
        f" | {len(unexpected)} unexpected | {len(not_found)} not found"
    )


def run_verify(token: str, chains: list[list[tuple[str, str]]]) -> int:
    """Run verification only, without creating or modifying dependencies.

    Args:
        token: Auth token.
        chains: List of reading order chains.

    Returns:
        Exit code: 0 if all present, 1 if any missing/unexpected/not_found.
    """
    print("\nVerifying dependencies...")
    result = verify_reading_order(chains, token)
    _print_verification_report(result)

    if not result["missing"] and not result["unexpected"] and not result["not_found"]:
        print("\n🎉 All dependencies verified successfully!")
        return 0
    return 1


def run_fix(token: str, chains: list[list[tuple[str, str]]]) -> int:
    """Verify first, then create only missing dependencies.

    Args:
        token: Auth token.
        chains: List of reading order chains.

    Returns:
        Exit code: 0 on success, 1 if issues remain after fix attempt.
    """
    print("\nVerifying dependencies...")
    result = verify_reading_order(chains, token)

    if not result["missing"]:
        _print_verification_report(result)
        if not result["unexpected"] and not result["not_found"]:
            print("\n🎉 All dependencies verified successfully!")
        return 0 if not result["unexpected"] and not result["not_found"] else 1

    print(f"  ❌ Found {len(result['missing'])} missing dependencies")
    print("\n🔧 Fetching issue IDs for fix...")

    all_threads = get_all_threads(token)

    thread_issue_ids: dict[str, dict[str, int]] = {}
    all_titles: set[str] = set()
    for chain_edges in chains:
        for title, _ in chain_edges:
            all_titles.add(title)

    for title in all_titles:
        if title in all_threads:
            issues = get_thread_issues(token, all_threads[title]["id"])
            thread_issue_ids[title] = issues

    fixed_count = 0
    for edge in result["missing"]:
        source_issues = thread_issue_ids.get(edge.source_title, {})
        target_issues = thread_issue_ids.get(edge.target_title, {})

        source_issue_id = source_issues.get(edge.source_issue)
        target_issue_id = target_issues.get(edge.target_issue)

        if source_issue_id is not None and target_issue_id is not None:
            if create_dependency(token, source_issue_id, target_issue_id):
                fixed_count += 1
                print(
                    f"  ✅ Fixed: {edge.source_title} #{edge.source_issue} -> {edge.target_title} #{edge.target_issue}"
                )
            else:
                print(
                    f"  ⚠️ Skipped (already exists): {edge.source_title} #{edge.source_issue} -> {edge.target_title} #{edge.target_issue}"
                )
        else:
            print(
                f"  🔍 Cannot fix (issue not in DB): {edge.source_title} #{edge.source_issue} -> {edge.target_title} #{edge.target_issue}"
            )

    print(f"\n✅ Fixed {fixed_count} dependencies")
    return 0 if fixed_count == len(result["missing"]) else 1


def run_create(token: str, chains: list[list[tuple[str, str]]]) -> int:
    """Create all dependencies (original behaviour).

    Args:
        token: Auth token.
        chains: List of reading order chains.

    Returns:
        Exit code: 0 on success.
    """
    print("\n📖 Checking existing threads...")
    existing_threads = get_all_threads(token)

    if "Planetary" in existing_threads:
        planetary_thread = existing_threads["Planetary"]
        next_unread = planetary_thread.get("next_unread_issue_number", "1")
        issues_read = int(next_unread) - 1 if next_unread else 0
        print(f"📖 Planetary exists: next unread is #{next_unread} (read #1-{issues_read})")

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

    thread_ids: dict[str, int] = {}
    for title, spec in thread_specs.items():
        if title in existing_threads:
            thread_id = existing_threads[title]["id"]
            print(f"  ✅ Using existing: {title}")
        else:
            print(f"  📚 Creating: {title}")
            thread_id = create_thread(token, title, spec.total_issues)

        thread_ids[title] = thread_id

        thread_info = existing_threads.get(title, {})
        if thread_info.get("total_issues") is None:
            try:
                migrate_thread(token, thread_id, len(spec.issues_to_mark_read), spec.total_issues)
            except requests.HTTPError as e:
                if e.response is not None and "already uses issue tracking" in e.response.text:
                    pass
                else:
                    print(f"  Migration issue for {title}: {e}")

    print("\n🔗 Fetching issue IDs...")
    print("=" * 70)

    thread_issue_ids: dict[str, dict[str, int]] = {}
    for title in thread_specs:
        thread_id = thread_ids[title]
        issues = get_thread_issues(token, thread_id)
        thread_issue_ids[title] = issues
        print(f"  {title}: {len(issues)} issues")

    print("\n🔗 Creating dependencies...")
    print("=" * 70)

    created_count = 0
    for chain in chains:
        for i in range(len(chain) - 1):
            source_title, source_issue = chain[i]
            target_title, target_issue = chain[i + 1]

            if source_issue in thread_issue_ids.get(
                source_title, {}
            ) and target_issue in thread_issue_ids.get(target_title, {}):
                source_issue_id = thread_issue_ids[source_title][source_issue]
                target_issue_id = thread_issue_ids[target_title][target_issue]

                if create_dependency(token, source_issue_id, target_issue_id):
                    created_count += 1
                    print(f"  🔗 {source_title} #{source_issue} -> {target_title} #{target_issue}")

    print("\n" + "=" * 70)
    print("📊 Summary")
    print("=" * 70)
    print(f"🔐 Dependencies created: {created_count}")

    chain_names = list(load_chains().keys())
    print("\nReading structure:")
    print(f"  {chain_names[0]}: STRICT ORDER (with WildC.A.T.s/Aliens block)")
    print(f"  {chain_names[1]}: Interleaved with hard blocks")
    print(f"  {chain_names[2]}: Crossovers + endgame (#24-26)")
    print("=" * 70)
    print("\n🎉 Warren Ellis Wildstorm reading order complete!")
    print("=" * 70)

    return 0


def main(argv: list[str] | None = None) -> int:
    """Main entry point.

    Args:
        argv: Command-line arguments. Defaults to sys.argv[1:].

    Returns:
        Exit code.
    """
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    chains = load_chains_as_list()

    print("Warren Ellis Wildstorm Reading Order")
    print("=" * 70)

    token = _authenticate()

    if args.verify:
        return run_verify(token, chains)
    elif args.fix:
        return run_fix(token, chains)
    else:
        return run_create(token, chains)


if __name__ == "__main__":
    sys.exit(main())
