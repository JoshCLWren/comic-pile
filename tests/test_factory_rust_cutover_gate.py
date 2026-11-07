"""End-to-end queue-selection regression for Rust-cutover-first factory work."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / ".github" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "factory_work_policy_rust_gate", SCRIPTS / "factory_work_policy.py"
)
assert SPEC is not None and SPEC.loader is not None
policy = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = policy
SPEC.loader.exec_module(policy)


def issue(number: int, *labels: str, body: str = "") -> dict:
    return {
        "number": number,
        "state": "OPEN",
        "labels": [{"name": label} for label in ("factory:unowned", *labels)],
        "body": body,
        "createdAt": "2026-11-07T01:00:00Z",
    }


def pr(number: int, linked: int, *, body: str = "") -> dict:
    return {
        "number": number,
        "state": "OPEN",
        "labels": [
            {"name": label}
            for label in ("factory", "factory:unowned", "factory:review")
        ],
        "headRefName": f"factory/46-{linked}-kilo-auto",
        "headRefOid": "a" * 40,
        "body": body,
        "createdAt": "2026-11-07T01:01:00Z",
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
    }


def numbers(issues: list[dict], prs: list[dict]) -> set[tuple[str, int]]:
    return {(item.kind, item.number) for item in policy.build_candidates(issues, prs)}


def test_new_unrelated_issue_waits_without_needing_body_rewrite() -> None:
    epic = issue(4335, "epic")
    assert numbers([epic, issue(4707)], []) == set()
    assert numbers([issue(4707)], []) == {("issue", 4707)}


def test_rust_cutover_issue_and_main_breakage_remain_executable() -> None:
    epic = issue(4335, "epic")
    allowed = issue(4707, "rust")
    breakage = issue(4709, "main-breakage")
    assert numbers([epic, allowed, breakage], []) == {
        ("issue", 4707),
        ("issue", 4709),
    }


def test_unrelated_open_pr_waits_even_if_it_predates_the_issue_dependency() -> None:
    epic = issue(4335, "epic")
    old_issue = issue(3507, body="Fix unrelated E2E inventory")
    candidate = pr(4704, 3507)
    assert numbers([epic, old_issue], [candidate]) == set()
    assert numbers([old_issue], [candidate]) == {("pr", 4704)}


def test_rust_pr_can_continue_review_and_repairs() -> None:
    epic = issue(4335, "epic")
    cutover_issue = issue(4346, "rust")
    assert numbers([epic, cutover_issue], [pr(4707, 4346)]) == {("pr", 4707)}


def test_deferred_dependency_overrides_rust_label_for_issues_and_prs() -> None:
    epic = issue(4335, "epic")
    deferred = issue(4516, "rust", body="Depends on #4335")
    assert numbers([epic, deferred], []) == set()
    assert numbers([epic, deferred], [pr(4700, 4516)]) == set()


def test_closing_reference_cannot_smuggle_unrelated_issue_through_rust_branch() -> None:
    epic = issue(4335, "epic")
    rust = issue(4346, "rust")
    unrelated = issue(4707)
    linked_pr = pr(4708, 4346, body="Closes #4707.")
    assert numbers([epic, rust, unrelated], [linked_pr]) == set()


def test_unlinked_pr_requires_explicit_rust_label_during_cutover() -> None:
    epic = issue(4335, "epic")
    orphan = pr(4708, 4707)
    assert numbers([epic], [orphan]) == set()
    orphan["labels"].append({"name": "rust"})
    assert numbers([epic], [orphan]) == set()  # branch still claims missing issue
    orphan["headRefName"] = "maintenance/rust-cutover"
    assert numbers([epic], [orphan]) == {("pr", 4708)}
