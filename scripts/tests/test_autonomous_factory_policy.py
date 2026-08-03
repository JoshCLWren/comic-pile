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
    """Verify closure-first factory drift is detected."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = CHECKER.POLICY.read_text(encoding="utf-8")
        cls.protocol = CHECKER.PROTOCOL.read_text(encoding="utf-8")
        cls.entrypoint = CHECKER.ENTRYPOINT.read_text(encoding="utf-8")

    def validate(self, *, policy: str | None = None, entrypoint: str | None = None) -> None:
        CHECKER.validate_texts(
            policy if policy is not None else self.policy,
            self.protocol,
            entrypoint if entrypoint is not None else self.entrypoint,
        )

    def test_current_policy_sources_are_aligned(self) -> None:
        self.validate()

    def test_issue_closure_north_star_is_required(self) -> None:
        mutated = self.policy.replace(
            "Finish what you start. Success is measured by issues closed, not pull requests opened.",
            "Success is measured by pull requests opened.",
        )
        with self.assertRaisesRegex(SystemExit, "missing required policy text"):
            self.validate(policy=mutated)

    def test_issue_ownership_is_required(self) -> None:
        mutated = self.policy.replace(
            "A worker owns an issue, not a PR.",
            "A worker owns one PR at a time.",
        )
        with self.assertRaisesRegex(SystemExit, "missing required policy text"):
            self.validate(policy=mutated)

    def test_planning_pr_ban_is_required(self) -> None:
        mutated = self.policy.replace(
            "Do not open planning-only, architecture-only, inventory-only, or implementation-plan PRs",
            "Planning PRs are encouraged",
        )
        with self.assertRaisesRegex(SystemExit, "missing required policy text"):
            self.validate(policy=mutated)

    def test_large_coherent_pr_rule_is_required(self) -> None:
        mutated = self.policy.replace(
            "Large coherent PRs are allowed and preferred",
            "Always split large PRs into stages",
        )
        with self.assertRaisesRegex(SystemExit, "missing required policy text"):
            self.validate(policy=mutated)

    def test_stage_fast_path_cannot_return(self) -> None:
        mutated = f"{self.entrypoint}\nHONEST STAGE FAST PATH\n"
        with self.assertRaisesRegex(SystemExit, "forbidden policy drift"):
            self.validate(entrypoint=mutated)

    def test_no_auto_merge_boundary_is_required(self) -> None:
        mutated = self.policy.replace(
            "Never enable auto-merge as a substitute for explicit authorization.",
            "Enable auto-merge after CI passes.",
        )
        with self.assertRaisesRegex(SystemExit, "missing required policy text"):
            self.validate(policy=mutated)

    def test_obsolete_marker_dialect_is_rejected(self) -> None:
        mutated = f"{self.policy}\n<!-- comic-pile-factory-fix-v2:legacy -->\n"
        with self.assertRaisesRegex(SystemExit, "forbidden policy drift"):
            self.validate(policy=mutated)

    def test_entrypoint_cannot_restore_merge_behavior(self) -> None:
        mutated = f"{self.entrypoint}\n# merge the pull request after CI\n"
        with self.assertRaisesRegex(SystemExit, "forbidden policy drift"):
            self.validate(entrypoint=mutated)


if __name__ == "__main__":
    unittest.main()
