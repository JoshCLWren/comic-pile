"""Regression tests for reader-facing release classification grounding."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "release_recovery.py"
SPEC = importlib.util.spec_from_file_location("release_recovery_grounding", SCRIPT_PATH)
assert SPEC and SPEC.loader
recovery = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = recovery
SPEC.loader.exec_module(recovery)


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


def run_public_guard(
    tmp_path: Path,
    candidate: dict[str, object],
    changed: list[str],
) -> tuple[dict[str, object], dict[str, object], MagicMock]:
    """Run the tracked pre-publication guard against one staged candidate."""
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(candidate), encoding="utf-8")
    args = argparse.Namespace(
        candidate=str(path),
        repository="JoshCLWren/comic-pile",
        pr=5748,
    )
    with (
        patch.object(recovery, "changed_file_names", return_value=changed) as files,
        patch.object(recovery, "_write_outputs") as outputs,
    ):
        assert recovery._verify_public(args) == 0
    written = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(written, dict)
    return written, outputs.call_args.args[0], files


def assert_internal_test_only(payload: dict[str, object]) -> None:
    """Require the durable internal provenance accepted by the trusted publisher."""
    assert payload["visibility"] == "internal"
    assert payload["status"] == "published"
    provenance = payload["provenance_json"]
    assert isinstance(provenance, dict)
    assert provenance["classification"] == "internal"
    assert "only test files" in str(provenance["classification_reason"])
    assert provenance["reader_reachable"] is False
    assert provenance["user_visible_evidence"] == ""
    assert provenance["inspected_issue_numbers"] == []
    assert provenance["scope_fences"] == []
    assert provenance["contradicting_evidence"] == []


def test_complete_test_only_diff_becomes_a_durable_internal_candidate(
    tmp_path: Path,
) -> None:
    """A model cannot talk its way around an observed test-only merged diff."""
    changed = ["frontend/src/unit/ThreadDetailView.test.tsx"]
    payload, output, _ = run_public_guard(tmp_path, public_candidate(), changed)

    assert_internal_test_only(payload)
    assert not recovery.is_public_publication(payload)
    assert recovery.test_only_public_violation(payload, changed) is None
    assert output == {
        "guard": "classified_internal",
        "reason": "test_only",
        "changed_files": 1,
    }


def test_contradicting_evidence_does_not_override_a_test_only_diff(
    tmp_path: Path,
) -> None:
    """Provenance prose cannot convert developer-only work into a reader feature."""
    candidate = public_candidate()
    provenance = candidate["provenance_json"]
    assert isinstance(provenance, dict)
    provenance["contradicting_evidence"] = ["An unsupported public classification claim."]

    payload, _, _ = run_public_guard(
        tmp_path,
        candidate,
        ["native/roll-service/tests/release_contract.rs"],
    )

    assert_internal_test_only(payload)


def test_internal_test_only_outcome_unblocks_the_next_missing_source(
    tmp_path: Path,
) -> None:
    """A persisted internal outcome lets oldest-first recovery make progress."""
    candidate = public_candidate()
    first = recovery.Source(
        number=5748,
        merged_at="2026-11-24T03:09:14Z",
        merge_commit_sha="5fedcb76fa1ad6d3f42b9599b0119df86953ba1d",
        title="Test-only fixture repair",
    )
    second = recovery.Source(
        number=5749,
        merged_at="2026-11-24T04:00:00Z",
        merge_commit_sha="a" * 40,
        title="Reader-visible fix",
    )
    payload, _, _ = run_public_guard(
        tmp_path,
        candidate,
        ["frontend/src/unit/ThreadDetailView.test.tsx"],
    )
    assert_internal_test_only(payload)

    persisted = [(first.number, first.merge_commit_sha)]
    assert recovery.select_missing_source([first, second], persisted) == second
    assert recovery.select_missing_source([first], persisted) is None


def test_product_change_with_regression_tests_remains_eligible(tmp_path: Path) -> None:
    """The guard does not rewrite a real frontend change accompanied by tests."""
    candidate = public_candidate()
    candidate["title"] = "Thread pages explain circular reading blockers"
    candidate["summary"] = "Readers can now understand why a circular reading rule blocks a series."
    changed = [
        "frontend/src/pages/ThreadDetailView.tsx",
        "frontend/src/unit/ThreadDetailView.test.tsx",
    ]

    payload, output, files = run_public_guard(tmp_path, candidate, changed)

    assert payload == candidate
    assert output == {"guard": "ok", "changed_files": 2}
    files.assert_called_once_with("JoshCLWren/comic-pile", 5748)


def test_full_bounded_file_page_does_not_prove_a_test_only_diff(tmp_path: Path) -> None:
    """A truncated file response cannot falsely fence an unseen product file."""
    candidate = public_candidate()
    changed = [f"frontend/src/unit/Example{number}.test.tsx" for number in range(100)]

    payload, output, _ = run_public_guard(tmp_path, candidate, changed)

    assert payload == candidate
    assert output == {"guard": "ok", "changed_files": 100}


def test_internal_candidate_skips_public_file_grounding(tmp_path: Path) -> None:
    """Durable internal skips do not incur public-classification API reads."""
    candidate = public_candidate()
    candidate["visibility"] = "internal"
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(candidate), encoding="utf-8")
    args = argparse.Namespace(
        candidate=str(path),
        repository="JoshCLWren/comic-pile",
        pr=5748,
    )

    with (
        patch.object(recovery, "changed_file_names") as files,
        patch.object(recovery, "_write_outputs") as outputs,
    ):
        assert recovery._verify_public(args) == 0

    files.assert_not_called()
    assert json.loads(path.read_text(encoding="utf-8")) == candidate
    assert outputs.call_args.args[0] == {"guard": "ok", "reason": "not_public"}


def test_test_only_rewrite_does_not_depend_on_model_provenance(tmp_path: Path) -> None:
    """Missing or malformed model provenance cannot strand the oldest source."""
    candidate = public_candidate()
    candidate["provenance_json"] = "unsupported public provenance"

    payload, _, _ = run_public_guard(
        tmp_path,
        candidate,
        ["frontend/src/unit/ThreadDetailView.test.tsx"],
    )

    assert_internal_test_only(payload)
