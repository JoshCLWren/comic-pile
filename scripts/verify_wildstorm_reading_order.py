#!/usr/bin/env python3
"""Verify Warren Ellis Wildstorm reading order dependencies.

Compares the expected reading order chains against the actual dependencies
stored in the Comic Pile API and prints a human-readable report.

Environment Variables:
    COMIC_PILE_USERNAME: Your username
    COMIC_PILE_PASSWORD: Your password

Usage:
    export COMIC_PILE_USERNAME=Josh_Digital_Comics
    export COMIC_PILE_PASSWORD=your_password
    python scripts/verify_wildstorm_reading_order.py
"""

import os
import sys

from comic_pile_api import VerificationResult, login, verify_reading_order
from create_wildstorm_reading_order import (
    planetary_authority_chain,
    planetary_late_chain,
    stormwatch_chain,
)


def print_report(result: VerificationResult) -> None:
    """Print a human-readable verification report.

    Args:
        result: Verification result dict with present, missing, unexpected lists.
    """
    present = result["present"]
    missing = result["missing"]
    unexpected = result["unexpected"]
    not_found = result["not_found"]

    print("\n" + "=" * 70)
    print("Verification Report")
    print("=" * 70)

    if present:
        print(f"\n✅ Present ({len(present)}):")
        for edge in present:
            print(
                f"   {edge.source_title} #{edge.source_issue} → {edge.target_title} #{edge.target_issue}"
            )

    if missing:
        print(f"\n❌ Missing ({len(missing)}):")
        for edge in missing:
            print(
                f"   {edge.source_title} #{edge.source_issue} → {edge.target_title} #{edge.target_issue}"
            )

    if unexpected:
        print(f"\n⚠️  Unexpected ({len(unexpected)}):")
        for edge in unexpected:
            print(
                f"   {edge.source_title} #{edge.source_issue} → {edge.target_title} #{edge.target_issue}"
            )

    if not_found:
        print(f"\n🔍 Not found in DB ({len(not_found)}):")
        for edge in not_found:
            print(
                f"   {edge.source_title} #{edge.source_issue} → {edge.target_title} #{edge.target_issue}"
            )

    print("\n" + "=" * 70)
    total = len(present) + len(missing) + len(unexpected) + len(not_found)
    print(
        f"Total: {total} edges | ✅ {len(present)} present | ❌ {len(missing)} missing"
        f" | ⚠️  {len(unexpected)} unexpected | 🔍 {len(not_found)} not found"
    )

    if not missing and not unexpected and not not_found:
        print("🎉 All dependencies verified successfully!")
    print("=" * 70)


def main() -> int:
    """Main entry point."""
    print("🔍 Verifying Warren Ellis Wildstorm Reading Order")
    print("=" * 70)

    username = os.environ.get("COMIC_PILE_USERNAME")
    password = os.environ.get("COMIC_PILE_PASSWORD")

    if not username or not password:
        print("❌ Error: Please set COMIC_PILE_USERNAME and COMIC_PILE_PASSWORD")
        return 1

    print("\n🔐 Authenticating...")
    token = login(username, password)
    print("✅ Authenticated")

    chains = [stormwatch_chain, planetary_authority_chain, planetary_late_chain]

    print("\n🔎 Verifying dependencies...")
    result = verify_reading_order(chains, token)
    print_report(result)

    return 1 if result["missing"] or result["unexpected"] or result["not_found"] else 0


if __name__ == "__main__":
    sys.exit(main())
