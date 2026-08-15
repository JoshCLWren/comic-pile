#!/usr/bin/env python3
"""Pure decision helper for fixed-model PR repair safety."""

from __future__ import annotations

import argparse
import json
import unittest

FACTORY_CONTROL_PREFIXES: tuple[str, ...] = (
    ".github/workflows/fixed-model-",
    ".github/workflows/free-model-factory-",
    ".github/scripts/fixed-model-",
    ".github/scripts/free-model-factory-",
    ".github/scripts/classify-fixed-model-run.py",
    ".github/scripts/validate-free-model-factories.py",
    ".github/free-model-factories.tsv",
)

FACTORY_TASK_NEEDLES: tuple[str, ...] = (
    "fixed-model",
    "free-model-factory",
    "factory fleet",
    "factory worker",
    "factory lease",
    "factory contamination",
    "factory guard",
    "factory dispatcher",
    "factory runner",
    "opencode-free-model-factory",
)


def is_factory_control_path(path: str) -> bool:
    """Return True when a path is fixed-model factory control infrastructure."""
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return any(
        normalized == prefix.rstrip("/") or normalized.startswith(prefix)
        for prefix in FACTORY_CONTROL_PREFIXES
    )


def task_allows_factory_control(title: str, body: str) -> bool:
    """Return True when the selected task explicitly concerns factory infrastructure."""
    text = f"{title}\n{body}".lower()
    return any(needle in text for needle in FACTORY_TASK_NEEDLES)


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


def reject_decision(
    previous_pr_files: set[str],
    latest_commit_files: set[str],
    *,
    title: str = "",
    body: str = "",
) -> dict[str, object]:
    """Decide whether a factory persistence attempt must be rejected.

    Rejection is fail-closed and deterministic:
    1. Zero overlap with an existing PR diff is rejected.
    2. Factory-control paths are rejected unless the selected task is about
       fixed-model factory infrastructure.

    Args:
        previous_pr_files: Paths already on the PR before local changes.
        latest_commit_files: Paths in the staged/uncommitted factory diff.
        title: Selected issue or PR title used for scope checks.
        body: Selected issue or PR body used for scope checks.

    Returns:
        JSON-serializable decision with reject flag and reason.

    """
    latest = set()
    for path in latest_commit_files:
        if not path:
            continue
        normalized = path.replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        latest.add(normalized)
    previous = set()
    for path in previous_pr_files:
        if not path:
            continue
        normalized = path.replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        previous.add(normalized)

    if unrelated_repair(previous, latest):
        return {
            "reject": True,
            "reason": "zero-overlap-with-existing-pr-diff",
            "factory_control_files": sorted(path for path in latest if is_factory_control_path(path)),
        }

    control_files = sorted(path for path in latest if is_factory_control_path(path))
    if control_files and not task_allows_factory_control(title, body):
        return {
            "reject": True,
            "reason": "factory-control-out-of-scope",
            "factory_control_files": control_files,
        }

    return {
        "reject": False,
        "reason": "allowed",
        "factory_control_files": control_files,
    }


class GuardTests(unittest.TestCase):
    """Unit tests for unrelated-repair and factory-control detection."""

    def test_unrelated_repair_is_rejected(self) -> None:
        """Zero-overlap repair on an existing PR is rejected."""
        decision = reject_decision(
            {".github/scripts/factory-visibility.cjs"},
            {"app/schemas/release.py"},
            title="After rating two d4s appear?",
            body="Duplicate dice on the roll screen.",
        )
        self.assertTrue(decision["reject"])
        self.assertEqual(decision["reason"], "zero-overlap-with-existing-pr-diff")

    def test_repair_with_overlap_is_allowed_even_with_new_tests(self) -> None:
        """Overlap with prior PR files allows the repair, including new tests."""
        decision = reject_decision(
            {"app/service.py"},
            {"app/service.py", "tests/test_service.py"},
            title="Fix service bug",
            body="Product bug",
        )
        self.assertFalse(decision["reject"])

    def test_first_implementation_commit_is_not_rejected(self) -> None:
        """Empty previous PR set means first implementation, not a repair."""
        decision = reject_decision(
            set(),
            {"app/new_feature.py"},
            title="Add feature",
            body="Product feature",
        )
        self.assertFalse(decision["reject"])

    def test_empty_latest_commit_is_not_rejected(self) -> None:
        """Empty latest commit is not treated as an unrelated repair."""
        decision = reject_decision(
            {"app/service.py"},
            set(),
            title="Fix service bug",
            body="Product bug",
        )
        self.assertFalse(decision["reject"])

    def test_mixed_factory_control_on_product_pr_is_rejected(self) -> None:
        """Factory control edits are rejected even when mixed with product overlap."""
        decision = reject_decision(
            {
                "frontend/src/components/Dice3D.tsx",
                "frontend/src/test/issue-1182-header-die-size.spec.ts",
            },
            {
                "frontend/src/test/issue-1182-header-die-size.spec.ts",
                ".github/scripts/classify-fixed-model-run.py",
                ".github/scripts/fixed-model-guard.py",
            },
            title="After raiting two d4s appear?",
            body="They're both rotating on the dice selection screen.",
        )
        self.assertTrue(decision["reject"])
        self.assertEqual(decision["reason"], "factory-control-out-of-scope")
        self.assertIn(".github/scripts/classify-fixed-model-run.py", decision["factory_control_files"])

    def test_factory_infra_task_may_edit_factory_control(self) -> None:
        """Tasks about the fixed-model fleet may touch factory control paths."""
        decision = reject_decision(
            {".github/scripts/fixed-model-guard.py"},
            {".github/scripts/fixed-model-guard.py", ".github/free-model-factories.tsv"},
            title="Guard fixed-model PR repairs and runner leases",
            body="Prevent fixed-model factory contamination across the factory fleet.",
        )
        self.assertFalse(decision["reject"])

    def test_legacy_unrelated_repair_helper_still_matches(self) -> None:
        """Preserve the original zero-overlap helper behavior."""
        self.assertTrue(
            unrelated_repair({".github/scripts/factory-visibility.cjs"}, {"app/schemas/release.py"})
        )
        self.assertFalse(unrelated_repair({"app/service.py"}, {"app/service.py", "tests/test_service.py"}))


def main() -> int:
    """CLI entrypoint for the repair guard decision or self-tests.

    Returns:
        Process exit code (0 on success).

    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--previous-json")
    parser.add_argument("--latest-json")
    parser.add_argument("--title", default="")
    parser.add_argument("--body", default="")
    args = parser.parse_args()

    if args.self_test:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(GuardTests)
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1

    previous = set(json.loads(args.previous_json or "[]"))
    latest = set(json.loads(args.latest_json or "[]"))
    print(json.dumps(reject_decision(previous, latest, title=args.title, body=args.body)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
