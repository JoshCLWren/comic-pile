#!/usr/bin/env python3
"""Post-merge issue closure for ComicPile factory merge automation.

Factory PRs are created, pushed, and merged with the Actions ``GITHUB_TOKEN``
inside workflow runs. GitHub never triggers workflows from its own token, so
the ``pull_request_target`` label reconciler never observes factory PR
lifecycles, and keyword auto-close has proven unreliable for these merges.
The result was systemic stranding: delivery PRs merged into ``main`` while
their linked issues stayed open under contradictory workflow labels forever,
because policy excludes ready-marked work from ordinary selection.

This module gives the ready merge drain a direct, idempotent closure step:

1. resolve the linked issue from the PR branch shape or closing keyword;
2. refuse protected operational issues;
3. atomically replace stale workflow-state, owner, and status labels with the
   merged-and-complete label set;
4. publish a durable closure marker comment;
5. close the issue as completed.

A ``--sweep`` mode heals any issue stranded by an older merge: it walks
recently merged factory PRs and applies the same closure to quiescent open
issues that no active work signal protects.

The canonical closure marker schema is::

    <!-- comic-pile-factory-merge-closure-v1:pr-<pr>:issue-<issue> -->

"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone

PROTECTED_ISSUES = frozenset({679, 1093, 1109})

FACTORY_LABEL = "factory"
DONE_STATUS_LABEL = "ralph-status:done"

OWNER_RE = re.compile(r"^factory:(?:unowned|local|[1-9]|[1-3][0-9]|[4-5][0-9])$")
ACTIVE_OWNER_RE = re.compile(r"^factory:(?:local|[1-9]|[1-3][0-9]|[4-5][0-9])$")
STAGE_LABELS = frozenset(
    {
        "factory:building",
        "factory:review",
        "factory:changes-requested",
        "factory:ci",
        "factory:ready",
        "factory:blocked",
    }
)
BLOCKED_STATUS_LABELS = frozenset({"ralph-status:blocked"})
RALPH_STATUS_RE = re.compile(r"^ralph-status:")

BRANCH_ISSUE_RE = re.compile(r"^factory/[0-9]+-(?P<issue>[0-9]+)-")
CLOSING_RE = re.compile(
    r"\b(?:closes|closed|close|fixes|fixed|fix|resolves|resolved|resolve)\s+#(?P<issue>[0-9]+)",
    re.IGNORECASE,
)

MERGE_CLOSURE_MARKER = "comic-pile-factory-merge-closure-v1"
SWEEP_MAX_AGE_HOURS = 26


def linked_issue(branch: str, body: str | None) -> int | None:
    """Resolve the issue a delivered PR closes.

    Args:
        branch: The PR head branch name; factory branches encode the issue.
        body: The PR body text, or None when unavailable.

    Returns:
        The issue number the PR claims to complete, or None when the branch
        does not match the factory shape and the body carries no closing
        keyword.
    """
    match = BRANCH_ISSUE_RE.match(branch or "")
    if match is not None:
        return int(match.group("issue"))
    closing = CLOSING_RE.search(body or "")
    if closing is not None:
        return int(closing.group("issue"))
    return None


def target_labels(current: list[str]) -> list[str]:
    """Build the merged-and-complete label set for a delivered issue.

    Args:
        current: The issue's current label names.

    Returns:
        The atomic replacement set: every unrelated label preserved, transient
        workflow-state, owner, and ralph-status labels removed, plus ``factory``
        and ``ralph-status:done``.
    """
    kept = [
        label
        for label in current
        if not OWNER_RE.match(label)
        and label not in STAGE_LABELS
        and not RALPH_STATUS_RE.match(label)
        and label != FACTORY_LABEL
    ]
    return kept + [FACTORY_LABEL, DONE_STATUS_LABEL]


def issue_is_quiescent(labels: list[str]) -> bool:
    """Return whether an open issue shows no signal of live continuation.

    A stale workflow-stage or ralph-status label on an issue whose delivery
    already merged is not liveness: the truthful liveness signals are a real
    next-action owner lease and an open successor PR, which the caller checks
    separately. Only genuine blockers refuse closure here.

    Args:
        labels: The issue's current label names.

    Returns:
        False when a real owner lease or a blocked marker is present; True
        otherwise, including contradictory stale stages like ``in-progress``
        alongside ``factory:ready`` under ``factory:unowned``.
    """
    for label in labels:
        if label in BLOCKED_STATUS_LABELS or label == "factory:blocked":
            return False
        if ACTIVE_OWNER_RE.match(label):
            return False
    return True


def closure_blocked_by_active_work(labels: list[str], require_quiescent: bool) -> bool:
    """Return whether closure must wait because the issue shows live work.

    Args:
        labels: The issue's current label names.
        require_quiescent: Whether the caller needs a quiescent issue.

    Returns:
        True when the caller requires quiescence and any active workflow
        stage, active ralph status, or blocked marker is present.
    """
    return require_quiescent and not issue_is_quiescent(labels)


def closure_comment(pr_number: int, issue_number: int) -> str:
    """Build the durable closure marker comment for a merged delivery PR.

    Args:
        pr_number: The merged PR number.
        issue_number: The linked issue number being closed.

    Returns:
        The comment text embedding the canonical merge-closure marker.
    """
    return (
        f"<!-- {MERGE_CLOSURE_MARKER}:pr-{pr_number}:issue-{issue_number} -->\n"
        f"Closed automatically: merge automation merged PR #{pr_number} through "
        "the exact-head factory gates, completing this issue's delivery contract."
    )


def merged_within_age(merged_at: str | None, now: datetime, max_age_hours: int) -> bool:
    """Return whether a PR merge timestamp falls inside the sweep window.

    Args:
        merged_at: The PR ``mergedAt`` ISO timestamp, or None when unknown.
        now: The current UTC time.
        max_age_hours: Inclusive age bound in hours.

    Returns:
        True when the timestamp parses and is no older than the bound.
    """
    if not merged_at:
        return False
    try:
        merged = datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if merged.tzinfo is None:
        merged = merged.replace(tzinfo=timezone.utc)
    return timedelta(0) <= now - merged <= timedelta(hours=max_age_hours)


def _run_gh(*args: str) -> str:
    """Run a gh CLI command and return stdout.

    Args:
        *args: gh arguments.

    Returns:
        Raw stdout from the command.

    Raises:
        RuntimeError: If gh exits nonzero.
    """
    completed = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout


def _repo_slug() -> str:
    """Return the owner/name repository slug for gh API calls.

    Returns:
        The repository slug from GITHUB_REPOSITORY or the local gh remotes.
    """
    slug = os.environ.get("GITHUB_REPOSITORY")
    if slug:
        return slug
    return _run_gh("repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner").strip()


def _pr_info(pr_number: int) -> dict[str, str]:
    """Fetch head branch, body, and merge state for one PR.

    Args:
        pr_number: The PR number.

    Returns:
        A dict with ``branch``, ``body``, and ``state`` string values.
    """
    raw = _run_gh(
        "pr",
        "view",
        str(pr_number),
        "--repo",
        _repo_slug(),
        "--json",
        "headRefName,body,state",
    )
    payload = json.loads(raw)
    return {
        "branch": str(payload.get("headRefName") or ""),
        "body": str(payload.get("body") or ""),
        "state": str(payload.get("state") or ""),
    }


def _issue_view(issue_number: int) -> dict[str, object]:
    """Fetch state and labels for one issue.

    Args:
        issue_number: The issue number.

    Returns:
        A dict with ``state`` (str) and ``labels`` (list[str]).
    """
    raw = _run_gh(
        "issue",
        "view",
        str(issue_number),
        "--repo",
        _repo_slug(),
        "--json",
        "state,labels",
    )
    payload = json.loads(raw)
    names = [str(label.get("name") or "") for label in payload.get("labels") or []]
    return {"state": str(payload.get("state") or ""), "labels": names}


def _issue_has_open_successor_pr(issue_number: int, merged_pr: int) -> bool:
    """Return whether another open PR also claims the issue.

    Args:
        issue_number: The issue number.
        merged_pr: The just-merged PR to exclude from the check.

    Returns:
        True when an open PR other than ``merged_pr`` links the issue by
        factory branch shape or closing keyword.
    """
    raw = _run_gh(
        "pr",
        "list",
        "--repo",
        _repo_slug(),
        "--state",
        "open",
        "--limit",
        "300",
        "--json",
        "number,headRefName,body",
    )
    for pr in json.loads(raw):
        number = int(pr.get("number") or 0)
        if number == merged_pr:
            continue
        if linked_issue(str(pr.get("headRefName") or ""), pr.get("body")) == issue_number:
            return True
    return False


def _replace_labels(issue_number: int, labels: list[str]) -> None:
    """Atomically replace an issue's label set.

    Args:
        issue_number: The issue number.
        labels: The complete target label set.
    """
    payload = json.dumps({"labels": labels})
    completed = subprocess.run(
        [
            "gh",
            "api",
            "--method",
            "PUT",
            f"repos/{_repo_slug()}/issues/{issue_number}/labels",
            "--input",
            "-",
        ],
        capture_output=True,
        text=True,
        input=payload,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"label replacement failed for issue {issue_number}: {completed.stderr.strip()}")


def _comment_issue(issue_number: int, body: str) -> None:
    """Publish one comment on an issue.

    Args:
        issue_number: The issue number.
        body: The comment text.
    """
    subprocess.run(
        [
            "gh",
            "api",
            "--method",
            "POST",
            f"repos/{_repo_slug()}/issues/{issue_number}/comments",
            "-f",
            f"body={body}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )


def _close_issue(issue_number: int) -> None:
    """Close an issue as completed.

    Args:
        issue_number: The issue number.
    """
    subprocess.run(
        [
            "gh",
            "api",
            "--method",
            "PATCH",
            f"repos/{_repo_slug()}/issues/{issue_number}",
            "-f",
            "state=closed",
            "-F",
            "state_reason=completed",
        ],
        capture_output=True,
        text=True,
        check=True,
    )


def close_merged_pr_issue(
    pr_number: int,
    *,
    dry_run: bool = False,
    require_quiescent: bool = False,
) -> str:
    """Close the issue delivered by one merged factory PR.

    Args:
        pr_number: The merged PR number.
        dry_run: When True, report the intended action without mutating GitHub.
        require_quiescent: When True, refuse closure when the issue carries any
            active-work or blocked signal. The sweep mode requires this because
            it re-examines old merges without fresh gate verification; direct
            post-merge closure omits it because the exact-head gates were just
            verified for the delivered scope.

    Returns:
        One of ``closed``, ``already-closed``, ``no-linked-issue``,
        ``protected-issue``, ``successor-open``, ``active-work``, or
        ``dry-run:<action>``.
    """
    info = _pr_info(pr_number)
    issue_number = linked_issue(info["branch"], info["body"])
    if issue_number is None:
        return "no-linked-issue"
    if issue_number in PROTECTED_ISSUES:
        return "protected-issue"

    issue = _issue_view(issue_number)
    if str(issue["state"]) != "OPEN":
        return "already-closed"

    labels = list(issue["labels"])
    if closure_blocked_by_active_work(labels, require_quiescent):
        return "active-work"
    if _issue_has_open_successor_pr(issue_number, pr_number):
        return "successor-open"

    if dry_run:
        return f"dry-run:replace-labels-with{target_labels(labels)}+close"
    _replace_labels(issue_number, target_labels(labels))
    _comment_issue(issue_number, closure_comment(pr_number, issue_number))
    _close_issue(issue_number)
    return "closed"


def sweep_stranded_closures(*, dry_run: bool = False, max_age_hours: int = SWEEP_MAX_AGE_HOURS) -> list[str]:
    """Heal issues stranded open by merges that predate direct closure.

    Args:
        dry_run: When True, report intended actions without mutating GitHub.
        max_age_hours: Only consider PRs merged within this many hours.

    Returns:
        One outcome line per examined merged factory PR.
    """
    raw = _run_gh(
        "pr",
        "list",
        "--repo",
        _repo_slug(),
        "--state",
        "merged",
        "--label",
        FACTORY_LABEL,
        "--limit",
        "100",
        "--json",
        "number,headRefName,body,mergedAt",
    )
    now = datetime.now(timezone.utc)
    outcomes: list[str] = []
    for pr in json.loads(raw):
        pr_number = int(pr.get("number") or 0)
        merged_at = pr.get("mergedAt")
        if not merged_within_age(str(merged_at) if merged_at else None, now, max_age_hours):
            continue
        outcome = close_merged_pr_issue(pr_number, dry_run=dry_run, require_quiescent=True)
        outcomes.append(f"PR {pr_number}: {outcome}")
    return outcomes


class FactoryPostMergeClosureTests(unittest.TestCase):
    """Cover pure closure resolution, labeling, and sweep gating logic."""

    def test_branch_shape_resolves_issue(self) -> None:
        """Parse the issue encoded in a factory branch name."""
        self.assertEqual(linked_issue("factory/39-1566-opencode-free", ""), 1566)
        self.assertEqual(linked_issue("factory/45-1399-opencode-free", "Closes #999."), 1399)

    def test_non_factory_branch_falls_back_to_body_keyword(self) -> None:
        """Use the closing keyword when the branch encodes nothing."""
        self.assertEqual(linked_issue("phase/some-work", "Closes #42."), 42)
        self.assertEqual(linked_issue("phase/some-work", "Fixes #7\nResolves #8"), 7)

    def test_unlinkable_pr_returns_none(self) -> None:
        """Return None without branch shape or a closing keyword."""
        self.assertIsNone(linked_issue("phase/some-work", "Refs #12 only"))
        self.assertIsNone(linked_issue("", ""))

    def test_target_labels_preserve_unrelated_and_add_done(self) -> None:
        """Strip transient factory state while keeping product labels."""
        self.assertEqual(
            target_labels(
                [
                    "bug",
                    "user-reported",
                    "factory",
                    "factory:ready",
                    "factory:unowned",
                    "ralph-status:validation",
                ]
            ),
            ["bug", "user-reported", "factory", "ralph-status:done"],
        )

    def test_target_labels_drop_every_stale_variant(self) -> None:
        """Remove all owner, stage, and status variants."""
        self.assertEqual(
            target_labels(
                [
                    "enhancement",
                    "factory:building",
                    "factory:review",
                    "factory:changes-requested",
                    "factory:ci",
                    "factory:blocked",
                    "factory:46",
                    "factory:local",
                    "ralph-status:in-progress",
                    "ralph-status:pending",
                ]
            ),
            ["enhancement", "factory", "ralph-status:done"],
        )

    def test_quiescent_ready_issue_allows_closure(self) -> None:
        """Ready-marked unowned issues are the stranded signature."""
        self.assertTrue(
            issue_is_quiescent(["bug", "user-reported", "factory", "factory:unowned", "factory:ready"])
        )

    def test_stale_active_labels_under_no_owner_allow_closure(self) -> None:
        """Contradictory stale stages without an owner lease are not liveness."""
        self.assertTrue(
            issue_is_quiescent(
                ["bug", "factory", "factory:unowned", "factory:ready", "ralph-status:in-progress"]
            )
        )
        self.assertTrue(issue_is_quiescent(["factory", "factory:unowned", "factory:review"]))
        self.assertTrue(issue_is_quiescent(["factory", "factory:unowned", "ralph-status:validation"]))

    def test_owner_leases_and_blockers_refuse_sweep_closure(self) -> None:
        """Real owner leases and genuine blockers stop the sweep."""
        self.assertFalse(issue_is_quiescent(["factory", "factory:building", "factory:46"]))
        self.assertFalse(issue_is_quiescent(["factory", "factory:local"]))
        self.assertFalse(issue_is_quiescent(["factory", "factory:blocked"]))
        self.assertFalse(issue_is_quiescent(["factory", "ralph-status:blocked"]))

    def test_protected_issues_are_never_closed(self) -> None:
        """Operational registry issues stay outside closure authority."""
        self.assertIn(1093, PROTECTED_ISSUES)
        self.assertIn(679, PROTECTED_ISSUES)
        self.assertIn(1109, PROTECTED_ISSUES)

    def test_closure_comment_embeds_canonical_marker(self) -> None:
        """The marker identifies both the PR and the issue durably."""
        comment = closure_comment(1588, 1111)
        self.assertIn(
            f"<!-- {MERGE_CLOSURE_MARKER}:pr-1588:issue-1111 -->",
            comment,
        )
        self.assertIn("PR #1588", comment)

    def test_merged_within_age_bounds(self) -> None:
        """Only parseable timestamps inside the inclusive window pass."""
        now = datetime(2026, 8, 21, tzinfo=timezone.utc)
        self.assertTrue(merged_within_age("2026-08-21T00:00:00Z", now, 26))
        self.assertTrue(merged_within_age("2026-08-20T00:00:00Z", now, 26))
        self.assertFalse(merged_within_age("2026-08-19T00:00:00Z", now, 26))
        self.assertFalse(merged_within_age(None, now, 26))
        self.assertFalse(merged_within_age("garbage", now, 26))

    def test_sweep_gates_on_active_work_but_direct_closure_does_not(self) -> None:
        """Quiescence is enforced only when the caller requires it."""
        active = ["factory", "factory:building", "factory:46"]
        self.assertTrue(closure_blocked_by_active_work(active, True))
        self.assertFalse(closure_blocked_by_active_work(active, False))
        self.assertFalse(closure_blocked_by_active_work(["factory", "factory:ready"], True))


def main() -> int:
    """Parse arguments and run closure, sweep, or self-test.

    Returns:
        Process exit code (0 on success).
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr", type=int)
    parser.add_argument("--sweep", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(FactoryPostMergeClosureTests)
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1

    if args.sweep:
        outcomes = sweep_stranded_closures(dry_run=args.dry_run)
        for line in outcomes:
            print(line)
        return 0

    if args.pr is None:
        parser.error("--pr or --sweep is required unless --self-test is used")
    print(close_merged_pr_issue(args.pr, dry_run=args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
