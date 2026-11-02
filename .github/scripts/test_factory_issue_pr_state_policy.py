#!/usr/bin/env python3
"""Regression tests for trusted factory issue-state precedence."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from factory_issue_pr_state_policy import (
    LEASE_ACTION_HOLD_AMBIGUOUS,
    LEASE_ACTION_HOLD_LOCAL,
    LEASE_ACTION_HOLD_NUMBERED,
    LEASE_ACTION_RECONCILE,
    body_blocks_reconciliation,
    issue_labels_block_reconciliation,
    lease_action_for_issue,
    lease_reconciliation_action,
    stage_from_trusted_prs,
)
from factory_work_policy import BLOCKED_LABELS


def _iso_timestamp(epoch: int) -> str:
    """Return a GitHub-style UTC timestamp for an epoch."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _issue_payload(labels: list[str], updated_at: str | None) -> dict[str, object]:
    """Build the decoded issue shape consumed by the lease policy."""
    return {"labels": [{"name": label} for label in labels], "updated_at": updated_at}


class FactoryIssuePrStatePolicyTests(unittest.TestCase):
    """Cover issue lifecycle precedence across trusted factory PR histories."""

    def test_merged_pr_plus_later_duplicate_open_stays_ready(self) -> None:
        """Keep completion when a later trusted duplicate PR is opened."""
        self.assertEqual(
            stage_from_trusted_prs([
                {"trusted": True, "merged": True, "state": "CLOSED"},
                {"trusted": True, "merged": False, "state": "OPEN"},
            ]),
            "factory:ready",
        )

    def test_merged_pr_plus_duplicate_closed_unmerged_stays_ready(self) -> None:
        """Keep completion when a later trusted duplicate closes unmerged."""
        self.assertEqual(
            stage_from_trusted_prs([
                {"trusted": True, "merged": True, "state": "CLOSED"},
                {"trusted": True, "merged": False, "state": "CLOSED"},
            ]),
            "factory:ready",
        )

    def test_open_trusted_pr_without_merged_history_is_review(self) -> None:
        """Put an issue in review when its trusted history has an open PR only."""
        self.assertEqual(
            stage_from_trusted_prs([
                {"trusted": True, "merged": False, "state": "CLOSED"},
                {"trusted": True, "merged": False, "state": "OPEN"},
            ]),
            "factory:review",
        )

    def test_only_closed_unmerged_attempts_are_claimable(self) -> None:
        """Return an issue to claimable backlog after all trusted attempts close."""
        self.assertEqual(
            stage_from_trusted_prs([
                {"trusted": True, "merged": False, "state": "CLOSED"},
            ]),
            "claimable",
        )

    def test_untrusted_factory_pr_does_not_affect_state(self) -> None:
        """Ignore untrusted factory-shaped PRs when deriving issue state."""
        self.assertEqual(
            stage_from_trusted_prs([
                {"trusted": False, "merged": True, "state": "CLOSED"},
                {"trusted": False, "merged": False, "state": "OPEN"},
            ]),
            "claimable",
        )

    def test_ralph_status_blocked_blocks_reconciliation(self) -> None:
        """Hold labels must skip factory label rewrites, including ralph-status:blocked."""
        self.assertTrue(
            issue_labels_block_reconciliation(
                ["factory", "factory:unowned", "ralph-status:blocked"]
            )
        )
        for label in BLOCKED_LABELS:
            self.assertTrue(issue_labels_block_reconciliation([label]), label)
        self.assertFalse(
            issue_labels_block_reconciliation(
                ["factory", "factory:unowned", "ralph-status:pending"]
            )
        )

    def test_manual_only_body_blocks_reconciliation(self) -> None:
        """A standalone manual-only PR body must skip factory label rewrites."""
        self.assertTrue(
            body_blocks_reconciliation(
                "<!-- factory-execution:manual-only -->\nHold this factory PR.\n"
            )
        )
        self.assertFalse(
            body_blocks_reconciliation("Ordinary autonomous factory work.\n")
        )
        self.assertFalse(
            body_blocks_reconciliation(
                "To opt out, use `<!-- factory-execution:manual-only -->`."
            )
        )
        self.assertTrue(body_blocks_reconciliation("Hold this factory PR.\nmanual-only\n"))
        self.assertFalse(body_blocks_reconciliation("Discussing a manual-only hold in prose.\n"))

    def test_fresh_local_lease_is_preserved(self) -> None:
        """A fresh local claim must not be erased by a historical-PR sweep."""
        now = 1_800_000_000
        self.assertEqual(
            lease_action_for_issue(
                _issue_payload(
                    ["factory", "factory:local", "factory:building"],
                    _iso_timestamp(now - 5),
                ),
                now_epoch=now,
            ),
            LEASE_ACTION_HOLD_LOCAL,
        )

    def test_unknown_local_activity_is_not_stale(self) -> None:
        """Unknown freshness evidence preserves the active local lease."""
        self.assertEqual(
            lease_action_for_issue(
                _issue_payload(["factory", "factory:local"], None),
                now_epoch=1_800_000_000,
            ),
            LEASE_ACTION_HOLD_LOCAL,
        )

    def test_provably_stale_local_lease_is_reconciled(self) -> None:
        """The shared local TTL still authorizes a provable release."""
        now = 1_800_000_000
        self.assertEqual(
            lease_action_for_issue(
                _issue_payload(
                    ["factory", "factory:local", "factory:building"],
                    _iso_timestamp(now - 3601),
                ),
                now_epoch=now,
            ),
            LEASE_ACTION_RECONCILE,
        )

    def test_numbered_lease_is_never_stolen_without_evidence(self) -> None:
        """A numbered owner belongs to the controller, not this sweep."""
        self.assertEqual(
            lease_action_for_issue(
                _issue_payload(
                    ["factory", "factory:7", "factory:building"],
                    _iso_timestamp(1_799_990_000),
                ),
                now_epoch=1_800_000_000,
            ),
            LEASE_ACTION_HOLD_NUMBERED,
        )

    def test_numbered_release_requires_authoritative_evidence(self) -> None:
        """Fixed-lease TTL applies only when active-worker state is known."""
        labels = ["factory", "factory:7", "factory:building"]
        self.assertEqual(
            lease_reconciliation_action(
                labels,
                latest_activity_epoch=1_799_999_099,
                now_epoch=1_800_000_000,
                active_fixed_workers=set(),
                has_unresolved_active_runs=False,
            ),
            LEASE_ACTION_RECONCILE,
        )
        self.assertEqual(
            lease_reconciliation_action(
                labels,
                latest_activity_epoch=1_799_990_000,
                now_epoch=1_800_000_000,
                active_fixed_workers={7},
                has_unresolved_active_runs=False,
            ),
            LEASE_ACTION_HOLD_NUMBERED,
        )

    def test_conflicting_owners_are_preserved(self) -> None:
        """Ambiguous ownership is held for operator review."""
        self.assertEqual(
            lease_action_for_issue(
                _issue_payload(["factory", "factory:local", "factory:7"], None),
                now_epoch=1_800_000_000,
            ),
            LEASE_ACTION_HOLD_AMBIGUOUS,
        )

    def test_released_owner_does_not_block_reconciliation(self) -> None:
        """factory:unowned is not an active lease."""
        self.assertEqual(
            lease_action_for_issue(
                _issue_payload(["factory", "factory:unowned", "factory:review"], None),
                now_epoch=1_800_000_000,
            ),
            LEASE_ACTION_RECONCILE,
        )


if __name__ == "__main__":
    unittest.main()
