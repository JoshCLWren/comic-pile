"""Regression tests for autonomous factory policy drift."""

import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKER_PATH = ROOT / "scripts" / "check-autonomous-factory-policy.py"
SPEC = spec_from_file_location("factory_policy_checker", CHECKER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load {CHECKER_PATH}")
CHECKER = module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


class AutonomousFactoryPolicyTests(unittest.TestCase):
    """Verify backlog, review, merge, and Chromium policy invariants."""

    @classmethod
    def setUpClass(cls) -> None:
        """Load all checked-in policy sources once for mutation tests."""
        cls.policy = CHECKER.POLICY.read_text(encoding="utf-8")
        cls.protocol = CHECKER.PROTOCOL.read_text(encoding="utf-8")
        cls.entrypoint = CHECKER.read_entrypoint_text()

    def validate(self, policy: str | None = None, entrypoint: str | None = None) -> None:
        """Validate optional mutations with unchanged companion sources."""
        CHECKER.validate_texts(
            policy if policy is not None else self.policy,
            self.protocol,
            entrypoint if entrypoint is not None else self.entrypoint,
        )

    def assert_policy_change_fails(self, original: str, replacement: str) -> None:
        """Assert replacing a required canonical invariant is rejected."""
        mutated = self.policy.replace(original, replacement)
        self.assertNotEqual(mutated, self.policy)
        with self.assertRaisesRegex(SystemExit, "missing required policy text"):
            self.validate(policy=mutated)

    def assert_runtime_rule_fails(self, rule: str) -> None:
        """Assert appending a contradictory runtime rule is rejected."""
        with self.assertRaisesRegex(SystemExit, "forbidden policy drift"):
            self.validate(entrypoint=f"{self.entrypoint}\n{rule}\n")

    def test_current_sources_are_aligned(self) -> None:
        """Accept the current V16 policy, protocol, and runtime prompt."""
        self.validate()

    def test_version_and_backlog_goal_are_required(self) -> None:
        """Require V16 and issue-backlog closure as the prime directive."""
        self.assert_policy_change_fails("Version: 16", "Version: 15")
        self.assert_policy_change_fails(
            "Drive the open issue backlog to zero",
            "Keep existing pull requests busy",
        )

    def test_user_reported_bug_priority_is_required(self) -> None:
        """Require the newest unclaimed user-reported bug to outrank PR orbiting."""
        self.assert_policy_change_fails(
            "The newest unclaimed open issue labeled both `user-reported` and `bug`.",
            "Any existing pull request.",
        )

    def test_throughput_and_single_owner_rules_are_required(self) -> None:
        """Require parallel issue throughput without duplicate ownership."""
        self.assert_policy_change_fails(
            "When fewer than four substantive implementation PRs are open",
            "When no pull requests are open",
        )
        self.assert_policy_change_fails(
            "At most one implementation worker may own an issue",
            "Any number of workers may own an issue",
        )

    def test_review_feedback_gate_is_required(self) -> None:
        """Require current review threads and prevent silent feedback override."""
        self.assert_policy_change_fails(
            "fetch review submissions and all current inline review threads",
            "inspect only the worker review",
        )
        self.assert_policy_change_fails(
            "A worker's own review conclusion does not silently override existing human or bot feedback.",
            "The worker review overrides all feedback.",
        )

    def test_gated_merge_and_expected_sha_are_required(self) -> None:
        """Require complete merge gates and exact expected-head protection."""
        self.assert_policy_change_fails(
            "Workers may merge a PR without asking again only after all of these gates are satisfied",
            "Workers may merge whenever convenient",
        )
        self.assert_policy_change_fails(
            "the worker supplies the exact expected head SHA",
            "the worker merges whichever head is current",
        )

    def test_chromium_backlog_zero_cycle_is_required(self) -> None:
        """Require deferred Chromium E2E without mandatory browser sprawl."""
        self.assert_policy_change_fails(
            "Issue #679 is excluded from ordinary executable-backlog selection",
            "Issue #679 outranks product bugs",
        )
        self.assert_policy_change_fails(
            "Firefox and WebKit may be run manually",
            "All browsers are mandatory",
        )

    def test_runtime_rejects_pr_orbit_rules(self) -> None:
        """Reject the two runtime rules that starved unclaimed issues."""
        self.assert_runtime_rule_fails(
            "Prefer finishing already-started issues over starting new ones."
        )
        self.assert_runtime_rule_fails(
            "Do not start a new issue while an owned issue has executable remaining work."
        )

    def test_runtime_rejects_bad_merge_rules(self) -> None:
        """Reject both never-merge and CI-only ungated merge behavior."""
        self.assert_runtime_rule_fails("Never merge.")
        self.assert_runtime_rule_fails("merge the pull request after CI")

    def test_runtime_rejects_ignored_feedback_and_browser_sprawl(self) -> None:
        """Reject ignored review findings and mandatory three-browser drift."""
        self.assert_runtime_rule_fails("ignore unresolved review threads")
        self.assert_runtime_rule_fails("Firefox + WebKit + Chromium")


if __name__ == "__main__":
    unittest.main()
