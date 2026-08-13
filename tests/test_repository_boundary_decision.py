"""Regression tests for the repository-boundary decision cross-links.

The canonical decision document for issue #640 lives at
``docs/architecture/repository-boundary-decision.md``. These tests pin
the cross-link invariants between that document and the architecture,
deployment, and React docs so future drift does not break discoverability
of the decision.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS = REPO_ROOT / "docs"
DECISION_PATH = DOCS / "architecture" / "repository-boundary-decision.md"
LANDING_PATH = DOCS / "REPO_BOUNDARY.md"
VERCEL_DEPLOYMENT_PATH = DOCS / "VERCEL_DEPLOYMENT.md"
VERCEL_ARCHITECTURE_PATH = DOCS / "VERCEL_ARCHITECTURE.md"
REACT_ARCHITECTURE_PATH = DOCS / "REACT_ARCHITECTURE.md"
README_PATH = REPO_ROOT / "README.md"
VERCEL_JSON_PATH = REPO_ROOT / "vercel.json"
COUPLING_SCRIPT_PATH = REPO_ROOT / "scripts" / "coupling_metrics.py"
COUPLING_TESTS_PATH = (
    REPO_ROOT / "scripts" / "tests" / "test_coupling_metrics.py"
)


class DecisionDocumentTests(unittest.TestCase):
    """Pin the canonical decision document structure."""

    def test_decision_document_exists(self) -> None:
        """The canonical decision document must exist."""
        self.assertTrue(
            DECISION_PATH.exists(),
            f"Missing decision document at {DECISION_PATH}",
        )

    def test_decision_document_states_outcome(self) -> None:
        """The decision document must state the chosen option."""
        text = DECISION_PATH.read_text(encoding="utf-8")
        self.assertRegex(text, r"Option 3")
        self.assertRegex(text, r"single source repository")

    def test_decision_document_rejects_option_2(self) -> None:
        """The decision document must explicitly reject Option 2."""
        text = DECISION_PATH.read_text(encoding="utf-8")
        self.assertRegex(text, r"Option 2 is rejected by the evidence")

    def test_decision_document_states_preview_out_of_scope(self) -> None:
        """The decision document must state Preview environments are out of scope."""
        text = DECISION_PATH.read_text(encoding="utf-8")
        self.assertIn("Vercel Preview environments are out of scope", text)

    def test_decision_document_has_reevaluation_trigger(self) -> None:
        """The decision document must define a measurable trigger."""
        text = DECISION_PATH.read_text(encoding="utf-8")
        self.assertRegex(text, r"Trigger for re-evaluation")
        self.assertRegex(text, r"25%")


class LandingPageTests(unittest.TestCase):
    """Pin the short landing page."""

    def test_landing_page_exists(self) -> None:
        """The short landing page must exist."""
        self.assertTrue(LANDING_PATH.exists())

    def test_landing_page_links_decision(self) -> None:
        """The landing page must link to the canonical decision."""
        text = LANDING_PATH.read_text(encoding="utf-8")
        self.assertIn("repository-boundary-decision.md", text)

    def test_landing_page_states_decision(self) -> None:
        """The landing page must state the decision in plain language."""
        text = LANDING_PATH.read_text(encoding="utf-8")
        self.assertIn("One repository", text)
        self.assertIn("No published OpenAPI package", text)
        self.assertIn("No Vercel Preview environments", text)


class CrossLinkTests(unittest.TestCase):
    """Pin the cross-links between architecture docs and the decision."""

    def test_vercel_deployment_links_landing(self) -> None:
        """``VERCEL_DEPLOYMENT.md`` must mention the boundary decision."""
        text = VERCEL_DEPLOYMENT_PATH.read_text(encoding="utf-8")
        self.assertTrue(
            "REPO_BOUNDARY.md" in text
            or "repository-boundary-decision.md" in text,
            "VERCEL_DEPLOYMENT.md must link to the repository boundary decision",
        )

    def test_vercel_deployment_states_preview_out_of_scope(self) -> None:
        """``VERCEL_DEPLOYMENT.md`` must state Preview environments are out of scope."""
        text = VERCEL_DEPLOYMENT_PATH.read_text(encoding="utf-8")
        self.assertIn("Preview", text)
        self.assertRegex(text, r"out of scope|do not add|no.*[Pp]review", text)

    def test_vercel_architecture_links_landing(self) -> None:
        """``VERCEL_ARCHITECTURE.md`` must link to the boundary decision."""
        text = VERCEL_ARCHITECTURE_PATH.read_text(encoding="utf-8")
        self.assertTrue(
            "REPO_BOUNDARY.md" in text
            or "repository-boundary-decision.md" in text,
            "VERCEL_ARCHITECTURE.md must link to the repository boundary decision",
        )

    def test_react_architecture_links_landing(self) -> None:
        """``REACT_ARCHITECTURE.md`` must link to the boundary decision."""
        text = REACT_ARCHITECTURE_PATH.read_text(encoding="utf-8")
        self.assertTrue(
            "REPO_BOUNDARY.md" in text
            or "repository-boundary-decision.md" in text,
            "REACT_ARCHITECTURE.md must link to the repository boundary decision",
        )

    def test_readme_links_landing(self) -> None:
        """``README.md`` must reference the repository boundary."""
        text = README_PATH.read_text(encoding="utf-8")
        self.assertTrue(
            "REPO_BOUNDARY.md" in text
            or "repository-boundary-decision.md" in text,
            "README.md must reference the repository boundary decision",
        )


class VercelConfigTests(unittest.TestCase):
    """Pin the Vercel configuration that disables Preview environments."""

    def test_vercel_json_disables_non_main_branches(self) -> None:
        """``vercel.json`` must keep Preview deployments disabled."""
        config = json.loads(VERCEL_JSON_PATH.read_text(encoding="utf-8"))
        git = config.get("git", {})
        deployment_enabled = git.get("deploymentEnabled", {})
        self.assertTrue(deployment_enabled.get("main"))
        for key, value in deployment_enabled.items():
            if key == "main":
                continue
            with self.subTest(branch=key):
                self.assertFalse(value)

    def test_vercel_json_routes_only_api_and_docs_to_function(self) -> None:
        """Only API and docs paths should be routed to the function."""
        config = json.loads(VERCEL_JSON_PATH.read_text(encoding="utf-8"))
        routes = config.get("routes", [])
        function_routes = {
            route["src"]
            for route in routes
            if route.get("dest") == "/api/index.py"
        }
        self.assertIn("/api(?:/.*)?", function_routes)
        self.assertIn("/(?:openapi\\.json|docs|redoc|health)", function_routes)


class CouplingToolTests(unittest.TestCase):
    """Pin the existence and runnability of the coupling tool."""

    def test_coupling_script_exists(self) -> None:
        """The coupling script must exist."""
        self.assertTrue(COUPLING_SCRIPT_PATH.exists())

    def test_coupling_tests_exist(self) -> None:
        """The coupling classifier tests must exist."""
        self.assertTrue(COUPLING_TESTS_PATH.exists())

    def test_coupling_script_documents_windows(self) -> None:
        """The coupling script must mention the supported windows."""
        text = COUPLING_SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("--months", text)

    def test_coupling_script_documents_buckets(self) -> None:
        """The coupling script must document its bucket labels."""
        text = COUPLING_SCRIPT_PATH.read_text(encoding="utf-8")
        for bucket in (
            "frontend_only",
            "generated_only",
            "backend_only",
            "both_dirs",
            "infra_only",
            "docs_only",
        ):
            with self.subTest(bucket=bucket):
                self.assertIn(bucket, text)


class AcceptanceContractTests(unittest.TestCase):
    """Pin the explicit acceptance criteria checklist."""

    def test_decision_marks_all_acceptance_items(self) -> None:
        """Every acceptance criterion from #640 must be checked."""
        text = DECISION_PATH.read_text(encoding="utf-8")
        for marker in (
            "Measure frontend/backend change coupling",
            "Compare CI, release, rollback",
            "Explicitly document that Vercel Preview",
            "Make one explicit repository-boundary decision",
            "If a split is selected",
            "Update architecture documentation",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_decision_reevaluation_threshold_is_25_percent(self) -> None:
        """The re-evaluation threshold must be 25% of rolling 90-day commits."""
        text = DECISION_PATH.read_text(encoding="utf-8")
        match = re.search(r"exceeds 25%.*?90-day", text, re.DOTALL)
        self.assertIsNotNone(
            match,
            "Decision document must define a 25% / 90-day re-evaluation trigger",
        )


if __name__ == "__main__":
    unittest.main()
