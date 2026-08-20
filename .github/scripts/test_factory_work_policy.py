#!/usr/bin/env python3
"""Regression coverage for completion-first factory queue policy."""
from __future__ import annotations

import unittest

from factory_work_policy import (
    FACTORY_NO_DIFF_RETRY_LIMIT,
    Candidate,
    build_candidates,
    order_candidates_for_worker,
)


def labels(*names: str) -> list[dict[str, str]]:
    return [{"name": name} for name in names]


def factory_pr(
    number: int,
    *,
    stage: str = "factory:review",
    worker: int = 20,
    linked_issue: int | None = None,
    mergeable: str = "MERGEABLE",
    merge_state: str = "CLEAN",
    owner: str = "factory:unowned",
    branch: str | None = None,
) -> dict[str, object]:
    issue = linked_issue if linked_issue is not None else 9000 + number
    return {
        "number": number,
        "state": "OPEN",
        "isDraft": False,
        "labels": labels("factory", owner, stage),
        "headRefName": branch or f"factory/{worker}-{issue}-test",
        "body": f"Worker: opencode-free-model-factory-{worker}",
        "createdAt": "2026-08-17T00:00:00Z",
        "mergeable": mergeable,
        "mergeStateStatus": merge_state,
    }


def issue(number: int, *extra_labels: str) -> dict[str, object]:
    return {
        "number": number,
        "state": "OPEN",
        "title": f"Issue {number}",
        "labels": labels("factory", "factory:unowned", *extra_labels),
        "createdAt": "2026-08-17T00:00:00Z",
    }


class CompletionFirstOrderingTests(unittest.TestCase):
    def test_conflicted_pr_beats_ci_changes_and_review(self) -> None:
        candidates = [
            Candidate("pr", 1, 3, 0, "", stage="factory:review"),
            Candidate("pr", 2, 3, 0, "", stage="factory:changes-requested"),
            Candidate("pr", 3, 3, 0, "", stage="factory:ci"),
            Candidate("pr", 4, 3, 0, "", stage="factory:review", conflicted=True),
        ]
        self.assertEqual(
            [item.number for item in order_candidates_for_worker(candidates, "10")],
            [4, 3, 2, 1],
        )

    def test_build_candidates_marks_github_conflict_state(self) -> None:
        candidates = build_candidates(
            [],
            [factory_pr(5, mergeable="CONFLICTING", merge_state="DIRTY")],
        )
        self.assertEqual(len(candidates), 1)
        self.assertTrue(candidates[0].conflicted)

    def test_dirty_merge_state_is_enough_to_mark_conflict(self) -> None:
        candidates = build_candidates(
            [],
            [factory_pr(5, mergeable="UNKNOWN", merge_state="DIRTY")],
        )
        self.assertTrue(candidates[0].conflicted)

    def test_non_review_worker_prefers_fresh_issue_to_review_queue(self) -> None:
        candidates = [
            Candidate("issue", 1, 3, 4, "2026-08-17T00:00:00Z"),
            Candidate(
                "pr",
                2,
                3,
                0,
                "2026-08-16T00:00:00Z",
                stage="factory:review",
                producer_worker="43",
            ),
        ]
        self.assertEqual(order_candidates_for_worker(candidates, "9")[0].number, 1)

    def test_review_capacity_worker_still_prefers_review_pr(self) -> None:
        candidates = [
            Candidate("issue", 1, 3, 4, "2026-08-17T00:00:00Z"),
            Candidate(
                "pr",
                2,
                3,
                0,
                "2026-08-16T00:00:00Z",
                stage="factory:review",
                producer_worker="43",
            ),
        ]
        self.assertEqual(order_candidates_for_worker(candidates, "10")[0].number, 2)

    def test_pr_stage_order_is_ci_then_changes_then_review(self) -> None:
        candidates = [
            Candidate("pr", 1, 3, 0, "", stage="factory:review"),
            Candidate("pr", 2, 3, 0, "", stage="factory:changes-requested"),
            Candidate("pr", 3, 3, 0, "", stage="factory:ci"),
        ]
        self.assertEqual(
            [item.number for item in order_candidates_for_worker(candidates, "10")],
            [3, 2, 1],
        )

    def test_urgent_issue_keeps_priority_over_nonurgent_repair_work(self) -> None:
        candidates = [
            Candidate("issue", 1, 1, 4, "", stage="factory:building"),
            Candidate("pr", 2, 5, 0, "", stage="factory:changes-requested"),
        ]
        self.assertEqual(order_candidates_for_worker(candidates, "9")[0].number, 1)

    def test_failed_ci_work_beats_ordinary_fresh_intake(self) -> None:
        candidates = [
            Candidate("issue", 1, 3, 4, "", stage="factory:building"),
            Candidate("pr", 2, 3, 0, "", stage="factory:ci"),
        ]
        self.assertEqual(order_candidates_for_worker(candidates, "9")[0].number, 2)

    def test_producer_cannot_semantically_review_own_pr(self) -> None:
        candidates = [
            Candidate(
                "pr",
                2,
                3,
                0,
                "",
                stage="factory:review",
                producer_worker="9",
            ),
            Candidate("issue", 1, 3, 0, ""),
        ]
        self.assertEqual(order_candidates_for_worker(candidates, "9")[0].number, 1)


class RetryBudgetTests(unittest.TestCase):
    def test_no_diff_issue_retries_until_budget_is_exhausted(self) -> None:
        target = issue(31)
        below_budget = build_candidates(
            [target],
            [],
            no_diff_attempts_by_issue={31: FACTORY_NO_DIFF_RETRY_LIMIT - 1},
        )
        exhausted = build_candidates(
            [target],
            [],
            no_diff_attempts_by_issue={31: FACTORY_NO_DIFF_RETRY_LIMIT},
        )
        self.assertTrue(any(item.kind == "issue" and item.number == 31 for item in below_budget))
        self.assertFalse(any(item.kind == "issue" and item.number == 31 for item in exhausted))

    def test_real_factory_blocked_label_remains_terminal(self) -> None:
        candidates = build_candidates(
            [issue(31, "factory:blocked")],
            [],
            no_diff_attempts_by_issue={31: 0},
        )
        self.assertFalse(candidates)


class WipCapTests(unittest.TestCase):
    def ready_queue(self) -> list[dict[str, object]]:
        return [
            factory_pr(100 + offset, stage="factory:ready", worker=20 + offset)
            for offset in range(5)
        ]

    def active_pr_wip(self) -> list[dict[str, object]]:
        return [
            factory_pr(
                200 + offset,
                stage="factory:review",
                worker=20 + offset,
                owner=f"factory:{20 + offset}",
            )
            for offset in range(5)
        ]

    def test_ready_pr_queue_does_not_starve_ordinary_issue(self) -> None:
        candidates = build_candidates([issue(1)], self.ready_queue())
        self.assertTrue(any(item.kind == "issue" and item.number == 1 for item in candidates))

    def test_active_worker_pr_wip_preserves_backpressure(self) -> None:
        candidates = build_candidates([issue(1)], self.active_pr_wip())
        self.assertFalse(any(item.kind == "issue" and item.number == 1 for item in candidates))

    def test_wip_cap_allows_user_reported_bug(self) -> None:
        candidates = build_candidates(
            [issue(1, "user-reported", "bug")],
            self.active_pr_wip(),
        )
        self.assertTrue(any(item.kind == "issue" and item.number == 1 for item in candidates))

    def test_wip_cap_allows_critical_issue(self) -> None:
        candidates = build_candidates(
            [issue(1, "ralph-priority:critical")],
            self.active_pr_wip(),
        )
        self.assertTrue(any(item.kind == "issue" and item.number == 1 for item in candidates))

    def test_ready_pr_is_not_worker_candidate(self) -> None:
        candidates = build_candidates([], [factory_pr(1, stage="factory:ready")])
        self.assertFalse(any(item.kind == "pr" and item.number == 1 for item in candidates))

    def test_human_branch_with_factory_label_is_not_factory_candidate(self) -> None:
        candidates = build_candidates(
            [],
            [factory_pr(1, branch="chatgpt/human-authored-fix")],
        )
        self.assertFalse(candidates)


if __name__ == "__main__":
    unittest.main()
