"""Regression tests for reader-facing release classification grounding."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "release_writer.py"
SPEC = importlib.util.spec_from_file_location("release_writer_grounding", SCRIPT_PATH)
assert SPEC and SPEC.loader
writer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = writer
SPEC.loader.exec_module(writer)


def public_candidate() -> dict[str, object]:
    """Return a valid public candidate resembling the observed test-only false positive."""
    return {
        "source_repository": "JoshCLWren/comic-pile",
        "source_pr_number": 5748,
        "source_merge_sha": "5fedcb76fa1ad6d3f42b9599b0119df86953ba1d",
        "merged_at": "2026-11-24T03:09:14Z",
        "released_at": "2026-11-24T03:09:14Z",
        "category": "bugfix",
        "title": "Fix TypeScript error in circular dependency blocker test fixture",
        "summary": (
            "The regression test now includes the required evaluator field, "
            "preventing a type error in the test suite."
        ),
        "provenance_json": {
            "classification": "public",
            "classification_reason": "The model incorrectly treated a test repair as product work.",
            "user_visible_evidence": (
                "The model claimed that maintaining the blocker behavior test was "
                "directly visible to readers."
            ),
            "reader_reachable": True,
            "inspected_issue_numbers": [3518],
            "scope_fences": [],
            "contradicting_evidence": [],
            "reader_reachable_path": "Thread page blocked-by section",
        },
    }


def test_complete_test_only_diff_cannot_be_published_as_public() -> None:
    """A model cannot talk its way around an observed test-only merged diff."""
    payload = writer._validate_release(json.dumps(public_candidate()))
    changed = [{"filename": "frontend/src/unit/ThreadDetailView.test.tsx"}]
    with (
        patch.object(writer, "_changed_files", return_value=changed),
        patch.object(writer, "_linked_scope_fences") as fences,
    ):
        with pytest.raises(SystemExit) as error:
            writer._validate_publish_grounding(payload)

    assert error.value.code == 2
    fences.assert_not_called()


def test_contradicting_evidence_does_not_override_a_test_only_diff() -> None:
    """Provenance prose cannot convert developer-only work into a reader feature."""
    candidate = public_candidate()
    provenance = candidate["provenance_json"]
    assert isinstance(provenance, dict)
    provenance["contradicting_evidence"] = ["An unsupported public classification claim."]
    payload = writer._validate_release(json.dumps(candidate))
    changed = [{"filename": "native/roll-service/tests/release_contract.rs"}]
    with patch.object(writer, "_changed_files", return_value=changed):
        with pytest.raises(SystemExit, match="") as error:
            writer._validate_publish_grounding(payload)
    assert error.value.code == 2


def test_product_change_with_regression_tests_remains_eligible() -> None:
    """The guard does not reject a real frontend change accompanied by tests."""
    candidate = public_candidate()
    candidate["title"] = "Thread pages explain circular reading blockers"
    candidate["summary"] = "Readers can now understand why a circular reading rule blocks a series."
    payload = writer._validate_release(json.dumps(candidate))
    changed = [
        {"filename": "frontend/src/pages/ThreadDetailView.tsx"},
        {"filename": "frontend/src/unit/ThreadDetailView.test.tsx"},
    ]
    with (
        patch.object(writer, "_changed_files", return_value=changed) as files,
        patch.object(writer, "_linked_scope_fences", return_value=[]),
    ):
        writer._validate_publish_grounding(payload)
    files.assert_called_once()


def test_full_bounded_file_page_does_not_prove_a_test_only_diff() -> None:
    """A truncated file response cannot falsely fence an unseen product file."""
    payload = writer._validate_release(json.dumps(public_candidate()))
    changed = [
        {"filename": f"frontend/src/unit/Example{number}.test.tsx"}
        for number in range(100)
    ]
    with (
        patch.object(writer, "_changed_files", return_value=changed),
        patch.object(writer, "_linked_scope_fences", return_value=[]),
    ):
        writer._validate_publish_grounding(payload)


def test_internal_candidate_skips_public_file_grounding() -> None:
    """Durable internal skips do not incur public-classification API reads."""
    candidate = public_candidate()
    candidate["visibility"] = "internal"
    payload = writer._validate_release(json.dumps(candidate))
    with patch.object(writer, "_changed_files") as files:
        writer._validate_publish_grounding(payload)
    files.assert_not_called()
