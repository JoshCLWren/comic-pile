#!/usr/bin/env python3
"""Pure decision helper for fixed-model PR repair safety."""

from __future__ import annotations

import argparse
import json
import unittest


def unrelated_repair(previous_pr_files: set[str], latest_commit_files: set[str]) -> bool:
    """Reject only an existing-PR repair whose latest commit has zero overlap.

    Empty previous PR diffs represent first implementation commits and are not
    treated as adopted-PR repair work.

    Args:
        previous_pr_files: Paths already present on the PR before the latest commit.
        latest_commit_files: Paths touched by the latest commit.

    Returns:
        True when the latest commit is an unrelated repair that should be rejected.
    """
    return bool(
        previous_pr_files
        and latest_commit_files
        and previous_pr_files.isdisjoint(latest_commit_files)
    )


class GuardTests(unittest.TestCase):
    """Unit tests for unrelated-repair detection."""

    def test_unrelated_repair_is_rejected(self) -> None:
        """Zero-overlap repair on an existing PR is rejected."""
        self.assertTrue(
            unrelated_repair({".github/scripts/factory-visibility.cjs"}, {"app/schemas/release.py"})
        )

    def test_repair_with_overlap_is_allowed_even_with_new_tests(self) -> None:
        """Overlap with prior PR files allows the repair, including new tests."""
        self.assertFalse(
            unrelated_repair({"app/service.py"}, {"app/service.py", "tests/test_service.py"})
        )

    def test_first_implementation_commit_is_not_rejected(self) -> None:
        """Empty previous PR set means first implementation, not a repair."""
        self.assertFalse(unrelated_repair(set(), {"app/new_feature.py"}))

    def test_empty_latest_commit_is_not_rejected(self) -> None:
        """Empty latest commit is not treated as an unrelated repair."""
        self.assertFalse(unrelated_repair({"app/service.py"}, set()))


def main() -> int:
    """CLI entrypoint for the repair guard decision or self-tests.

    Returns:
        Process exit code (0 on success).
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--previous-json")
    parser.add_argument("--latest-json")
    args = parser.parse_args()

    if args.self_test:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(GuardTests)
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1

    previous = set(json.loads(args.previous_json or "[]"))
    latest = set(json.loads(args.latest_json or "[]"))
    print(json.dumps({"reject": unrelated_repair(previous, latest)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
