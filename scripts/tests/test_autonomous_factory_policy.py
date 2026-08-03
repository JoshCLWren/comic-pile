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
    """Verify canonical policy drift is detected rather than silently accepted."""

    @classmethod
    def setUpClass(cls) -> None:
        """Load the repository's canonical policy sources once for mutation tests."""
        cls.policy = CHECKER.POLICY.read_text(encoding="utf-8")
        cls.protocol = CHECKER.PROTOCOL.read_text(encoding="utf-8")
        cls.entrypoint = CHECKER.ENTRYPOINT.read_text(encoding="utf-8")

    def test_current_policy_sources_are_aligned(self) -> None:
        """Accept the checked-in canonical policy sources."""
        CHECKER.validate_texts(self.policy, self.protocol, self.entrypoint)

    def test_missing_builder_first_floor_is_rejected(self) -> None:
        """Reject removal of the durable-progress floor from canonical policy."""
        mutated = self.policy.replace(
            "Labels, claims, comments, verdicts, PR-body edits, and ready markers "
            "do not satisfy this floor by themselves.",
            "Coordination evidence may satisfy the floor.",
        )

        with self.assertRaisesRegex(SystemExit, "missing required policy text"):
            CHECKER.validate_texts(mutated, self.protocol, self.entrypoint)

    def test_missing_no_auto_merge_boundary_is_rejected(self) -> None:
        """Reject removal of the explicit no-auto-merge safety boundary."""
        mutated = self.policy.replace(
            "Never enable auto-merge as a substitute for explicit authorization.",
            "Auto-merge may be enabled after CI passes.",
        )

        with self.assertRaisesRegex(SystemExit, "missing required policy text"):
            CHECKER.validate_texts(mutated, self.protocol, self.entrypoint)

    def test_missing_exact_sha_truth_is_rejected(self) -> None:
        """Reject policy drift that allows approval evidence to float across commits."""
        mutated = self.policy.replace(
            "All review, repair, and readiness decisions are tied to the exact "
            "pull-request head SHA.",
            "Reviews may apply to later pull-request commits when the scope is similar.",
        )

        with self.assertRaisesRegex(SystemExit, "missing required policy text"):
            CHECKER.validate_texts(mutated, self.protocol, self.entrypoint)

    def test_obsolete_marker_dialect_is_rejected(self) -> None:
        """Reject reintroduction of an obsolete repair marker dialect."""
        mutated = f"{self.policy}\n<!-- comic-pile-factory-fix-v2:legacy -->\n"

        with self.assertRaisesRegex(SystemExit, "forbidden policy drift"):
            CHECKER.validate_texts(mutated, self.protocol, self.entrypoint)

    def test_protocol_cannot_restore_draft_pr_guidance(self) -> None:
        """Reject protocol drift that drops the non-draft boundary."""
        mutated = self.protocol.replace(
            "Never create a draft pull request unless Josh explicitly requests a draft.",
            "Draft pull requests are preferred.",
        )

        with self.assertRaisesRegex(SystemExit, "missing required policy text"):
            CHECKER.validate_texts(self.policy, mutated, self.entrypoint)

    def test_entrypoint_cannot_restore_merge_behavior(self) -> None:
        """Reject local-entrypoint drift that reintroduces merge instructions."""
        mutated = f"{self.entrypoint}\n# merge the pull request after CI\n"

        with self.assertRaisesRegex(SystemExit, "forbidden policy drift"):
            CHECKER.validate_texts(self.policy, self.protocol, mutated)


if __name__ == "__main__":
    unittest.main()
