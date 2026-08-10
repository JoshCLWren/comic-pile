"""Regression tests for the automatic OpenCode reviewer safety contract."""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPENCODE_CONFIG = ROOT / "opencode.json"
OPENCODE_WORKFLOW = ROOT / ".github" / "workflows" / "opencode.yml"


class OpenCodeReviewPolicyTests(unittest.TestCase):
    """Protect structural read-only review and atomic factory metadata updates."""

    def test_reviewer_cannot_edit_or_run_arbitrary_shell_commands(self) -> None:
        """Require structural denial of edits and arbitrary shell execution."""
        config = json.loads(OPENCODE_CONFIG.read_text(encoding="utf-8"))
        permission = config["permission"]
        self.assertEqual(permission["edit"], "deny")
        self.assertEqual(permission["question"], "deny")
        self.assertEqual(permission["bash"]["*"], "deny")
        self.assertEqual(
            permission["bash"]["gh api --method POST repos/*/pulls/*/comments*"],
            "allow",
        )

    def test_workflow_reconciles_labels_atomically_and_preserves_owner(self) -> None:
        """Reject sequential stage mutation or owner-dropping label replacement."""
        workflow = OPENCODE_WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("gh api --method DELETE", workflow)
        self.assertIn('^factory:(unowned|local|[1-5])$', workflow)
        self.assertIn('first // "factory:unowned"', workflow)
        self.assertGreaterEqual(workflow.count('gh api --method POST'), 2)
        self.assertGreaterEqual(workflow.count('"factory", $owner'), 2)

    def test_reviewer_has_no_merge_or_label_mutation_command(self) -> None:
        """Keep automatic review limited to posting inline findings."""
        config = json.loads(OPENCODE_CONFIG.read_text(encoding="utf-8"))
        allowed_bash = {
            command
            for command, decision in config["permission"]["bash"].items()
            if decision == "allow"
        }
        self.assertFalse(any("merge" in command for command in allowed_bash))
        self.assertFalse(any("labels" in command for command in allowed_bash))


if __name__ == "__main__":
    unittest.main()
