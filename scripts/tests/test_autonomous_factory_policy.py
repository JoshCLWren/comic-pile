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
    """Verify no-early-exit factory drift is detected."""

    @classmethod
    def setUpClass(cls) -> None:
        """Load the checked-in policy sources once for mutation tests."""
        cls.policy = CHECKER.POLICY.read_text(encoding="utf-8")
        cls.protocol = CHECKER.PROTOCOL.read_text(encoding="utf-8")
        cls.entrypoint = CHECKER.ENTRYPOINT.read_text(encoding="utf-8")

    def validate(self, *, policy: str | None = None, entrypoint: str | None = None) -> None:
        """Validate optional mutated text against unchanged companion sources."""
        CHECKER.validate_texts(
            policy if policy is not None else self.policy,
            self.protocol,
            entrypoint if entrypoint is not None else self.entrypoint,
        )

    def test_current_policy_sources_are_aligned(self) -> None:
        """Accept the checked-in canonical policy sources."""
        self.validate()

    def test_no_early_exit_north_star_is_required(self) -> None:
        """Reject returning to commit-sized heartbeat completion."""
        mutated = self.policy.replace(
            "Finish the issue. Do not stop at a commit, PR, review, CI run, or ready marker.",
            "Stop after one substantive commit.",
        )
        with self.assertRaisesRegex(SystemExit, "missing required policy text"):
            self.validate(policy=mutated)

    def test_mandatory_continue_check_is_required(self) -> None:
        """Reject removing the post-action continuation decision."""
        mutated = self.policy.replace(
            "Is there executable work remaining for this owned issue that I can safely do now?",
            "Was one commit pushed?",
        )
        with self.assertRaisesRegex(SystemExit, "missing required policy text"):
            self.validate(policy=mutated)

    def test_remaining_work_cannot_be_a_stop_report(self) -> None:
        """Reject allowing workers to list executable work and leave."""
        mutated = self.policy.replace(
            "Merely naming remaining work proves the opposite and requires continuing.",
            "List remaining work before stopping.",
        )
        with self.assertRaisesRegex(SystemExit, "missing required policy text"):
            self.validate(policy=mutated)

    def test_one_commit_is_not_a_stop_condition(self) -> None:
        """Reject restoring one-commit heartbeat completion."""
        mutated = self.policy.replace(
            "One pushed commit, pending CI, green CI, review completion, a large diff, or harder next work are never stop conditions.",
            "A heartbeat may stop after one substantive commit",
        )
        with self.assertRaisesRegex(SystemExit, "missing required policy text"):
            self.validate(policy=mutated)

    def test_planning_pr_ban_is_required(self) -> None:
        """Reject restoring planning-only PRs as normal delivery."""
        mutated = self.policy.replace(
            "Never open planning-only, architecture-only, inventory-only, or implementation-plan PRs",
            "Planning PRs are encouraged",
        )
        with self.assertRaisesRegex(SystemExit, "missing required policy text"):
            self.validate(policy=mutated)

    def test_large_coherent_pr_rule_is_required(self) -> None:
        """Reject restoring automatic stage splitting."""
        mutated = self.policy.replace(
            "Implement the whole issue in one coherent non-draft PR whenever reasonably reviewable.",
            "Always split large PRs into stages",
        )
        with self.assertRaisesRegex(SystemExit, "missing required policy text"):
            self.validate(policy=mutated)

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
