#!/usr/bin/env python3
"""Pure decision helpers for fixed-model fleet safety guards."""

from __future__ import annotations

import argparse
import json
import unittest

MAX_RUN_SECONDS = 2400


def unrelated_repair(previous_pr_files: set[str], latest_commit_files: set[str]) -> bool:
    """Reject only an existing-PR repair whose latest commit has zero overlap.

    Empty previous PR diffs represent first implementation commits and are not
    treated as adopted-PR repair work.
    """
    return bool(previous_pr_files and latest_commit_files and previous_pr_files.isdisjoint(latest_commit_files))


def over_runtime_budget(age_seconds: int, status: str) -> bool:
    return status == "in_progress" and age_seconds >= MAX_RUN_SECONDS


class GuardTests(unittest.TestCase):
    def test_unrelated_repair_is_rejected(self) -> None:
        self.assertTrue(unrelated_repair({".github/scripts/factory-visibility.cjs"}, {"app/schemas/release.py"}))

    def test_repair_with_overlap_is_allowed_even_with_new_tests(self) -> None:
        self.assertFalse(unrelated_repair({"app/service.py"}, {"app/service.py", "tests/test_service.py"}))

    def test_first_implementation_commit_is_not_rejected(self) -> None:
        self.assertFalse(unrelated_repair(set(), {"app/new_feature.py"}))

    def test_empty_latest_commit_is_not_rejected(self) -> None:
        self.assertFalse(unrelated_repair({"app/service.py"}, set()))

    def test_runtime_budget(self) -> None:
        self.assertFalse(over_runtime_budget(2399, "in_progress"))
        self.assertTrue(over_runtime_budget(2400, "in_progress"))
        self.assertFalse(over_runtime_budget(9999, "completed"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--previous-json")
    parser.add_argument("--latest-json")
    parser.add_argument("--age-seconds", type=int)
    parser.add_argument("--status", default="in_progress")
    args = parser.parse_args()

    if args.self_test:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(GuardTests)
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1

    if args.age_seconds is not None:
        print(json.dumps({"cancel": over_runtime_budget(args.age_seconds, args.status), "max_seconds": MAX_RUN_SECONDS}))
        return 0

    previous = set(json.loads(args.previous_json or "[]"))
    latest = set(json.loads(args.latest_json or "[]"))
    print(json.dumps({"reject": unrelated_repair(previous, latest)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
