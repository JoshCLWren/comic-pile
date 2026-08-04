"""Regression tests for the autonomous factory policy drift checker."""

import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKER_PATH = ROOT / "scripts" / "check-autonomous-factory-policy.py"
SPEC = spec_from_file_location("autonomous_factory_policy_checker", CHECKER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load policy checker from {CHECKER_PATH}")
CHECKER = module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


class AutonomousFactoryPolicyTests(unittest.TestCase):
    """Verify V15 throughput and anti-loop policy drift is detected."""

    @classmethod
    def setUpClass(cls) -> None:
        """Load the checked-in policy sources once for mutation tests."""
        cls.policy = CHECKER.POLICY.read_text(encoding="utf-8")
        cls.protocol = CHECKER.PROTOCOL.read_text(encoding="utf-8")
        cls.entrypoint = CHECKER.read_entrypoint_text()

    def validate(self, *, policy: str | None = None, entrypoint: str | None = None) -> None:
        """Validate optional mutated text against unchanged companion sources."""
        CHECKER.validate_texts(
            policy if policy is not None else self.policy,
            self.protocol,
            entrypoint if entrypoint is not None else self.entrypoint,
        )

    def assert_policy_mutation_fails(self, original: str, replacement: str) -> None:
        """Assert replacing one required policy invariant is rejected."""
        mutated = self.policy.replace(original, replacement)
        self.assertNotEqual(mutated, self.policy)
        with self.assertRaisesRegex(SystemExit, "missing required policy text"):
            self.validate(policy=mutated)

    def test_current_policy_sources_are_aligned(self) -> None:
        """Accept the checked-in canonical policy sources."""
        self.validate()

    def test_v15_version_is_required(self) -> None:
        """Reject a checker-policy pair that silently falls back to V11."""
        self.assert_policy_mutation_fails("Version: 15", "Version: 11")

    def test_throughput_floor_is_required(self) -> None:
        """Reject removing the fresh-implementation throughput preference."""
        self.assert_policy_mutation_fails(
            "When fewer than four substantive implementation PRs are open",
            "When no pull requests are open",
        )

    def test_ready_prs_are_excluded_from_selection(self) -> None:
        """Reject allowing green waiting PRs to monopolize workers."""
        self.assert_policy_mutation_fails(
            "A green, ready, review-passed, or Josh-waiting PR is excluded from work selection.",
            "A green PR may always receive more cleanup.",
        )

    def test_impossible_claims_do_not_loop(self) -> None:
        """Reject repeated claims whose next edit cannot run in the current runtime."""
        self.assert_policy_mutation_fails(
            "Do not repeatedly claim an issue whose next required edit is impossible in the current runtime.",
            "Retry blocked issues on every heartbeat.",
        )

    def test_main_advancing_does_not_force_replacement_prs(self) -> None:
        """Reject replacement PR churn caused only by new main commits."""
        self.assert_policy_mutation_fails(
            "Do not create replacement PRs merely because `main` advanced.",
            "Create a replacement PR whenever `main` advances.",
        )

    def test_single_worker_issue_ownership_is_required(self) -> None:
        """Reject duplicate implementation ownership without file separation."""
        self.assert_policy_mutation_fails(
            "At most one implementation worker may own an issue",
            "Any number of workers may edit the same issue",
        )

    def test_waiting_is_not_a_global_stop_condition(self) -> None:
        """Reject stopping the workforce while unrelated executable work exists."""
        self.assert_policy_mutation_fails(
            "Waiting for CI, Josh, review, a safer runtime, or a merge is not a global stop condition",
            "Waiting for CI stops all workers",
        )

    def test_large_coherent_pr_rule_is_required(self) -> None:
        """Reject restoring automatic stage splitting."""
        self.assert_policy_mutation_fails(
            "Implement the whole issue in one coherent non-draft PR whenever reasonably reviewable.",
            "Always split large PRs into stages",
        )

    def test_stage_fast_path_cannot_return(self) -> None:
        """Reject reintroducing the obsolete stage fast path."""
        mutated = f"{self.entrypoint}\nHONEST STAGE FAST PATH\n"
        with self.assertRaisesRegex(SystemExit, "forbidden policy drift"):
            self.validate(entrypoint=mutated)

    def test_entrypoint_cannot_restore_merge_behavior(self) -> None:
        """Reject local entrypoint instructions to merge autonomously."""
        mutated = f"{self.entrypoint}\n# merge the pull request after CI\n"
        with self.assertRaisesRegex(SystemExit, "forbidden policy drift"):
            self.validate(entrypoint=mutated)


if __name__ == "__main__":
    unittest.main()
