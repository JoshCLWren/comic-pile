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
    """Verify backlog, release-note, review, merge, and Chromium policy invariants."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = CHECKER.POLICY.read_text(encoding="utf-8")
        cls.protocol = CHECKER.PROTOCOL.read_text(encoding="utf-8")
        cls.entrypoint = CHECKER.read_entrypoint_text()

    def validate(
        self,
        policy: str | None = None,
        protocol: str | None = None,
        entrypoint: str | None = None,
    ) -> None:
        CHECKER.validate_texts(
            policy if policy is not None else self.policy,
            protocol if protocol is not None else self.protocol,
            entrypoint if entrypoint is not None else self.entrypoint,
        )

    def assert_policy_change_fails(self, original: str, replacement: str) -> None:
        mutated = self.policy.replace(original, replacement)
        self.assertNotEqual(mutated, self.policy)
        with self.assertRaisesRegex(SystemExit, "missing required policy text"):
            self.validate(policy=mutated)

    def assert_protocol_change_fails(self, original: str, replacement: str) -> None:
        mutated = self.protocol.replace(original, replacement)
        self.assertNotEqual(mutated, self.protocol)
        with self.assertRaisesRegex(SystemExit, "missing required policy text"):
            self.validate(protocol=mutated)

    def assert_runtime_rule_fails(self, rule: str) -> None:
        with self.assertRaisesRegex(SystemExit, "forbidden policy drift"):
            self.validate(entrypoint=f"{self.entrypoint}\n{rule}\n")

    def test_current_sources_are_aligned(self) -> None:
        self.validate()
        CHECKER.validate_local_guidance()

    def test_version_and_backlog_goal_are_required(self) -> None:
        self.assert_policy_change_fails("Version: 21", "Version: 20")
        self.assert_policy_change_fails(
            "Drive the open issue backlog to zero",
            "Keep existing pull requests busy",
        )

    def test_no_self_pause_and_e2e_fallback_are_required(self) -> None:
        self.assert_policy_change_fails(
            "An empty or blocked ordinary backlog is never an idle condition",
            "A blocked backlog may be treated as idle",
        )
        self.assert_policy_change_fails(
            "If no ordinary executable issue can be selected, do not declare the factory idle.",
            "If no ordinary executable issue can be selected, stop the factory.",
        )
        self.assert_policy_change_fails(
            "Blocked work never authorizes a worker to pause or disable itself.",
            "Blocked work may pause the worker.",
        )
        mutated = self.entrypoint.replace(
            "Never treat an empty or blocked backlog as a reason to idle, pause, disable yourself, or stop checking.",
            "A blocked backlog may stop the worker.",
        )
        self.assertNotEqual(mutated, self.entrypoint)
        with self.assertRaisesRegex(SystemExit, "missing required policy text"):
            self.validate(entrypoint=mutated)

    def test_user_reported_bug_priority_is_required(self) -> None:
        self.assert_policy_change_fails(
            "The newest unclaimed open issue labeled both `user-reported` and `bug`.",
            "Any existing pull request.",
        )

    def test_throughput_and_single_owner_rules_are_required(self) -> None:
        self.assert_policy_change_fails(
            "When fewer than four substantive implementation PRs are open",
            "When no pull requests are open",
        )
        self.assert_policy_change_fails(
            "At most one implementation worker may own an issue",
            "Any number of workers may own an issue",
        )

    def test_database_release_note_ownership_is_required(self) -> None:
        self.assert_policy_change_fails(
            "Release notes are asynchronous post-merge infrastructure",
            "Release notes are implementation merge gates",
        )
        self.assert_policy_change_fails(
            "Implementation workers must not create, repair, or require `docs/changelog.d` fragments",
            "Implementation workers must create changelog fragments",
        )
        self.assert_policy_change_fails(
            "not runtime truth",
            "runtime truth",
        )
        self.assert_runtime_rule_fails(
            "Treat the generated changelog as part of the completion contract"
        )
        self.assert_runtime_rule_fails("docs/changelog.d/YYYY-MM-DD-<pr-number>.md")
        self.assert_runtime_rule_fails("Changelog: not user-facing")

    def test_review_feedback_gate_is_required(self) -> None:
        self.assert_policy_change_fails(
            "fetch review submissions and all current inline review threads",
            "inspect only the worker review",
        )
        self.assert_policy_change_fails(
            "A worker's own review conclusion does not silently override existing human or bot feedback.",
            "The worker review overrides all feedback.",
        )

    def test_gated_merge_and_expected_sha_are_required(self) -> None:
        self.assert_policy_change_fails(
            "Workers may merge a PR without asking again only after all of these gates are satisfied",
            "Workers may merge whenever convenient",
        )
        self.assert_policy_change_fails(
            "the worker supplies the exact expected head SHA",
            "the worker merges whichever head is current",
        )

    def test_protocol_requires_exact_head_review_and_green_checks(self) -> None:
        self.assert_protocol_change_fails(
            "Before pass, readiness, or merge, inspect the exact current head SHA",
            "Before merge, inspect any recent commit",
        )
        self.assert_protocol_change_fails(
            "green on every required check",
            "green on at least one check",
        )

    def test_protocol_requires_feedback_and_expected_head_merge(self) -> None:
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
        self.assert_policy_change_fails(
            "Issue #679 is excluded from ordinary executable-backlog selection",
            "Issue #679 outranks product bugs",
        )
        self.assert_policy_change_fails(
            "Firefox and WebKit may be run manually",
            "All browsers are mandatory",
        )

    def test_runtime_rejects_pr_orbit_rules(self) -> None:
        self.assert_runtime_rule_fails(
            "Prefer finishing already-started issues over starting new ones."
        )
        self.assert_runtime_rule_fails(
            "Do not start a new issue while an owned issue has executable remaining work."
        )

    def test_runtime_rejects_bad_merge_rules(self) -> None:
        self.assert_runtime_rule_fails("Never merge.")
        self.assert_runtime_rule_fails("merge the pull request after CI")

    def test_runtime_rejects_ignored_feedback_and_browser_sprawl(self) -> None:
        self.assert_runtime_rule_fails("ignore unresolved review threads")
        self.assert_runtime_rule_fails("Firefox + WebKit + Chromium")

    def test_resume_packet_and_atomic_labels_are_required(self) -> None:
        self.assert_policy_change_fails("<!-- factory-resume:v1 -->", "<!-- resume -->")
        self.assert_policy_change_fails(
            "one full label-set replacement",
            "several label mutations",
        )

    def test_external_heartbeat_cannot_count_as_progress(self) -> None:
        self.assert_policy_change_fails(
            "Heartbeat telemetry never counts as substantive progress",
            "Heartbeat telemetry satisfies a scheduled run",
        )
        self.assert_policy_change_fails(
            "registry issue #1093",
            "an unspecified registry",
        )

    def test_runtime_rejects_hook_bypass_and_failed_test_commits(self) -> None:
        self.assert_runtime_rule_fails("core.hooksPath=/dev/null")
        self.assert_runtime_rule_fails("commit even if tests are not fully passing")


if __name__ == "__main__":
    unittest.main()
