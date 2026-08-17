#!/usr/bin/env python3
"""Regression coverage for completion-first factory queue policy."""
from __future__ import annotations

import unittest

from factory_work_policy import Candidate, build_candidates, order_candidates_for_worker


def labels(*names: str) -> list[dict[str, str]]:
    return [{"name": name} for name in names]


def factory_pr(
    number: int,
    *,
    stage: str = "factory:review",
    worker: int = 20,
    linked_issue: int | None = None,
) -> dict[str, object]:
    issue = linked_issue if linked_issue is not None else 9000 + number
    return {
        "number": number,
        "state": "OPEN",
        "isDraft": False,
        "labels": labels("factory", "factory:unowned", stage),
        "headRefName": f"factory/{worker}-{issue}-test",
        "body": f"Worker: opencode-free-model-factory-{worker}",
        "createdAt": "2026-08-17T00:00:00Z",
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
    def test_review_pr_beats_ordinary_issue_for_non_review_worker(self) -> None:
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
        self.assertEqual(order_candidates_for_worker(candidates, "9")[0].number, 2)

    def test_pr_stage_order_is_ci_then_changes_then_review(self) -> None:
        candidates = [
            Candidate("pr", 1, 3, 0, "", stage="factory:review"),
            Candidate("pr", 2, 3, 0, "", stage="factory:changes-requested"),
            Candidate("pr", 3, 3, 0, "", stage="factory:ci"),
        ]
        self.assertEqual(
            [item.number for item in order_candidates_for_worker(candidates, "9")],
            [3, 2, 1],
        )

    def test_urgent_issue_still_waits_behind_pr_completion(self) -> None:
        candidates = [
            Candidate("issue", 1, 1, 4, "", stage="factory:building"),
            Candidate("pr", 2, 5, 0, "", stage="factory:review"),
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


class WipCapTests(unittest.TestCase):
    def full_wip(self) -> list[dict[str, object]]:
        return [
            factory_pr(100 + offset, stage="factory:ready", worker=20 + offset)
            for offset in range(5)
        ]

    def test_wip_cap_suppresses_ordinary_issue(self) -> None:
        candidates = build_candidates([issue(1)], self.full_wip())
        self.assertFalse(any(item.kind == "issue" and item.number == 1 for item in candidates))

    def test_wip_cap_suppresses_infrastructure_issue(self) -> None:
        candidates = build_candidates(
            [issue(1, "infrastructure", "ralph-priority:high")],
            self.full_wip(),
        )
        self.assertFalse(any(item.kind == "issue" and item.number == 1 for item in candidates))

    def test_wip_cap_allows_user_reported_bug(self) -> None:
        candidates = build_candidates(
            [issue(1, "user-reported", "bug")],
            self.full_wip(),
        )
        self.assertTrue(any(item.kind == "issue" and item.number == 1 for item in candidates))

    def test_wip_cap_allows_critical_issue(self) -> None:
        candidates = build_candidates(
            [issue(1, "ralph-priority:critical")],
            self.full_wip(),
        )
        self.assertTrue(any(item.kind == "issue" and item.number == 1 for item in candidates))

    def test_ready_pr_is_not_worker_candidate(self) -> None:
        candidates = build_candidates([], [factory_pr(1, stage="factory:ready")])
        self.assertFalse(any(item.kind == "pr" and item.number == 1 for item in candidates))


if __name__ == "__main__":
    unittest.main()
