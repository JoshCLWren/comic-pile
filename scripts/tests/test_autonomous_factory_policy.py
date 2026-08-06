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
    """Verify backlog, changelog, review, merge, and Chromium policy invariants."""

    @classmethod
    def setUpClass(cls) -> None:
        """Load all checked-in policy sources once for mutation tests.

        Args:
            cls: Test class receiving the cached source texts.

        Returns:
            None.
        """
        cls.policy = CHECKER.POLICY.read_text(encoding="utf-8")
        cls.protocol = CHECKER.PROTOCOL.read_text(encoding="utf-8")
        cls.entrypoint = CHECKER.read_entrypoint_text()

    def validate(
        self,
        policy: str | None = None,
        protocol: str | None = None,
        entrypoint: str | None = None,
    ) -> None:
        """Validate optional mutations with unchanged companion sources.

        Args:
            policy: Optional replacement canonical policy text.
            protocol: Optional replacement issue execution protocol text.
            entrypoint: Optional replacement combined runtime prompt text.

        Returns:
            None.
        """
        CHECKER.validate_texts(
            policy if policy is not None else self.policy,
            protocol if protocol is not None else self.protocol,
            entrypoint if entrypoint is not None else self.entrypoint,
        )

    def assert_policy_change_fails(self, original: str, replacement: str) -> None:
        """Assert replacing a required canonical invariant is rejected.

        Args:
            original: Required text currently present in the policy.
            replacement: Mutated text that should fail validation.

        Returns:
            None.
        """
        mutated = self.policy.replace(original, replacement)
        self.assertNotEqual(mutated, self.policy)
        with self.assertRaisesRegex(SystemExit, "missing required policy text"):
            self.validate(policy=mutated)

    def assert_protocol_change_fails(self, original: str, replacement: str) -> None:
        """Assert weakening a required protocol gate is rejected.

        Args:
            original: Required text currently present in the protocol.
            replacement: Mutated text that should fail validation.

        Returns:
            None.
        """
        mutated = self.protocol.replace(original, replacement)
        self.assertNotEqual(mutated, self.protocol)
        with self.assertRaisesRegex(SystemExit, "missing required policy text"):
            self.validate(protocol=mutated)

    def assert_runtime_rule_fails(self, rule: str) -> None:
        """Assert appending a contradictory runtime rule is rejected.

        Args:
            rule: Contradictory runtime instruction to append.

        Returns:
            None.
        """
        with self.assertRaisesRegex(SystemExit, "forbidden policy drift"):
            self.validate(entrypoint=f"{self.entrypoint}\n{rule}\n")

    def test_current_sources_are_aligned(self) -> None:
        """Accept the current V17 policy, protocol, and runtime prompt.

        Returns:
            None.
        """
        self.validate()

    def test_version_and_backlog_goal_are_required(self) -> None:
        """Require V16 and issue-backlog closure as the prime directive.

        Returns:
            None.
        """
        self.assert_policy_change_fails("Version: 17", "Version: 16")
        self.assert_policy_change_fails(
            "Drive the open issue backlog to zero",
            "Keep existing pull requests busy",
        )

    def test_user_reported_bug_priority_is_required(self) -> None:
        """Require user-reported bugs to outrank PR orbiting.

        Returns:
            None.
        """
        self.assert_policy_change_fails(
            "The newest unclaimed open issue labeled both `user-reported` and `bug`.",
            "Any existing pull request.",
        )

    def test_throughput_and_single_owner_rules_are_required(self) -> None:
        """Require parallel issue throughput without duplicate ownership.

        Returns:
            None.
        """
        self.assert_policy_change_fails(
            "When fewer than four substantive implementation PRs are open",
            "When no pull requests are open",
        )
        self.assert_policy_change_fails(
            "At most one implementation worker may own an issue",
            "Any number of workers may own an issue",
        )

    def test_user_facing_changelog_gate_is_required(self) -> None:
        """Require release notes before factory readiness or merge.

        Returns:
            None.
        """
        self.assert_policy_change_fails(
            "Every product, behavior, deployment, operational, or factory-tooling PR must update",
            "Factory pull requests may skip release notes",
        )
        self.assert_policy_change_fails(
            "A missing required changelog entry is an actionable review defect",
            "Changelog omissions do not block merge",
        )

    def test_review_feedback_gate_is_required(self) -> None:
        """Require current review threads and prevent silent override.

        Returns:
            None.
        """
        self.assert_policy_change_fails(
            "fetch review submissions and all current inline review threads",
            "inspect only the worker review",
        )
        self.assert_policy_change_fails(
            "A worker's own review conclusion does not silently override existing human or bot feedback.",
            "The worker review overrides all feedback.",
        )

    def test_gated_merge_and_expected_sha_are_required(self) -> None:
        """Require complete merge gates and expected-head protection.

        Returns:
            None.
        """
        self.assert_policy_change_fails(
            "Workers may merge a PR without asking again only after all of these gates are satisfied",
            "Workers may merge whenever convenient",
        )
        self.assert_policy_change_fails(
            "the worker supplies the exact expected head SHA",
            "the worker merges whichever head is current",
        )

    def test_protocol_requires_exact_head_review_and_green_checks(self) -> None:
        """Reject protocol drift that weakens review or CI gates.

        Returns:
            None.
        """
        self.assert_protocol_change_fails(
            "Before pass, readiness, or merge, inspect the exact current head SHA",
            "Before merge, inspect any recent commit",
        )
        self.assert_protocol_change_fails(
            "green on every required check",
            "green on at least one check",
        )

    def test_protocol_requires_feedback_and_expected_head_merge(self) -> None:
        """Reject protocol drift that ignores findings or moved heads.

        Returns:
            None.
        """
        self.assert_protocol_change_fails(
            "An unresolved actionable correctness, security, ownership, data-integrity, migration, concurrency, recovery, or test-validity finding blocks readiness and merge.",
            "Unresolved findings may be ignored.",
        )
        self.assert_protocol_change_fails(
            "The merge operation must include the exact expected head SHA.",
            "The merge may target whichever head is current.",
        )
        self.assert_protocol_change_fails(
            "Never enable auto-merge.",
            "Auto-merge may be enabled after CI starts.",
        )

    def test_chromium_backlog_zero_cycle_is_required(self) -> None:
        """Require deferred Chromium E2E without browser sprawl.

        Returns:
            None.
        """
        self.assert_policy_change_fails(
            "Issue #679 is excluded from ordinary executable-backlog selection",
            "Issue #679 outranks product bugs",
        )
        self.assert_policy_change_fails(
            "Firefox and WebKit may be run manually",
            "All browsers are mandatory",
        )

    def test_runtime_rejects_pr_orbit_rules(self) -> None:
        """Reject runtime rules that starve unclaimed issues.

        Returns:
            None.
        """
        self.assert_runtime_rule_fails(
            "Prefer finishing already-started issues over starting new ones."
        )
        self.assert_runtime_rule_fails(
            "Do not start a new issue while an owned issue has executable remaining work."
        )

    def test_runtime_rejects_bad_merge_rules(self) -> None:
        """Reject both never-merge and CI-only merge behavior.

        Returns:
            None.
        """
        self.assert_runtime_rule_fails("Never merge.")
        self.assert_runtime_rule_fails("merge the pull request after CI")

    def test_runtime_rejects_ignored_feedback_and_browser_sprawl(self) -> None:
        """Reject ignored review findings and three-browser drift.

        Returns:
            None.
        """
        self.assert_runtime_rule_fails("ignore unresolved review threads")
        self.assert_runtime_rule_fails("Firefox + WebKit + Chromium")


if __name__ == "__main__":
    unittest.main()
