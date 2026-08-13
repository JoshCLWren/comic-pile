"""Regression tests for the coupling metrics classifier.

These tests pin the surface-classification rules so future maintenance
work cannot silently drift the metric. The repository-boundary decision
document for issue #640 depends on these rules being stable.
"""

from __future__ import annotations

import unittest

from scripts.coupling_metrics import (
    BACKEND_PREFIXES,
    FRONTEND_GENERATED_PREFIX,
    FRONTEND_PREFIX,
    _classify,
    _label_for,
)


class ClassifyTests(unittest.TestCase):
    """Pin the surface classification rules."""

    def test_frontend_only_path(self) -> None:
        """Frontend source paths classify as ``frontend``."""
        surfaces = _classify(["frontend/src/pages/RollPage/index.tsx"])
        self.assertEqual(surfaces, ("frontend",))

    def test_generated_only_path(self) -> None:
        """Generated OpenAPI artifacts classify as ``generated``."""
        surfaces = _classify(["frontend/src/generated/openapi.ts"])
        self.assertEqual(surfaces, ("generated",))

    def test_backend_only_paths(self) -> None:
        """All backend roots classify as ``backend``."""
        for prefix in BACKEND_PREFIXES:
            with self.subTest(prefix=prefix):
                surfaces = _classify([f"{prefix}foo.py"])
                self.assertEqual(surfaces, ("backend",))

    def test_both_dirs_mix(self) -> None:
        """A commit touching both surfaces classifies as both."""
        surfaces = _classify(
            ["frontend/src/services/api.ts", "app/api/roll.py"]
        )
        self.assertEqual(surfaces, ("backend", "frontend"))

    def test_infra_path(self) -> None:
        """CI/infra files classify as ``infra``."""
        surfaces = _classify([".github/workflows/ci.yml"])
        self.assertEqual(surfaces, ("infra",))

    def test_docs_path(self) -> None:
        """Documentation paths classify as ``docs``."""
        surfaces = _classify(["docs/REACT_ARCHITECTURE.md"])
        self.assertEqual(surfaces, ("docs",))

    def test_known_root_md_files(self) -> None:
        """Top-level Markdown files classify as ``docs``."""
        surfaces = _classify(["README.md"])
        self.assertEqual(surfaces, ("docs",))

    def test_unknown_path(self) -> None:
        """Unknown surfaces classify as ``other``."""
        surfaces = _classify(["random/strange/file.txt"])
        self.assertEqual(surfaces, ("other",))

    def test_infra_does_not_shadow_backend(self) -> None:
        """Backend code that also touches infra still includes backend."""
        surfaces = _classify(
            ["app/api/roll.py", ".github/workflows/ci.yml"]
        )
        self.assertIn("backend", surfaces)
        self.assertIn("infra", surfaces)


class LabelTests(unittest.TestCase):
    """Pin the bucket label mapping."""

    def test_both_dirs_label(self) -> None:
        """Touching both surfaces maps to ``both_dirs``."""
        self.assertEqual(_label_for(("backend", "frontend")), "both_dirs")

    def test_generated_only_label(self) -> None:
        """A pure regenerated commit maps to ``generated_only``."""
        self.assertEqual(_label_for(("generated",)), "generated_only")

    def test_frontend_only_label(self) -> None:
        """Pure frontend code maps to ``frontend_only``."""
        self.assertEqual(_label_for(("frontend",)), "frontend_only")

    def test_backend_only_label(self) -> None:
        """Pure backend code maps to ``backend_only``."""
        self.assertEqual(_label_for(("backend",)), "backend_only")

    def test_infra_only_label(self) -> None:
        """Pure infra/CI maps to ``infra_only``."""
        self.assertEqual(_label_for(("infra",)), "infra_only")

    def test_docs_only_label(self) -> None:
        """Pure docs map to ``docs_only``."""
        self.assertEqual(_label_for(("docs",)), "docs_only")

    def test_infra_with_docs_is_other(self) -> None:
        """Mixed infra + docs maps to ``other``."""
        self.assertEqual(_label_for(("docs", "infra")), "other")

    def test_prefix_constants_match_directory_layout(self) -> None:
        """The classifier prefixes must match the real layout."""
        self.assertTrue(FRONTEND_PREFIX.endswith("/"))
        self.assertTrue(FRONTEND_GENERATED_PREFIX.endswith("/"))
        self.assertTrue(FRONTEND_GENERATED_PREFIX.startswith(FRONTEND_PREFIX))
        for prefix in BACKEND_PREFIXES:
            with self.subTest(prefix=prefix):
                self.assertTrue(prefix.endswith("/"))


if __name__ == "__main__":
    unittest.main()
