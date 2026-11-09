"""CI-discovered regressions for #3271 semantic review handoff evidence."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / ".github" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def load_controller() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "factory_review_handoff_regression", SCRIPTS / "factory-review-controller.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_large_diff_never_replaces_actionable_review_finding() -> None:
    controller = load_controller()
    finding = "Missing authorization check exposes private creator metadata to another user."
    diff = "diff --git a/app.py b/app.py\n" + "+    return unsafe_code()\n" * 4000
    review_log = (
        finding + "\nFACTORY_GATE_BLOCKED\n"
        + controller.AUTHORITATIVE_DIFF_EVIDENCE
        + "\ngh pr diff 3200\n" + diff
    )

    excerpt = controller.semantic_review_excerpt(review_log)

    assert finding in excerpt
    assert "gh pr diff 3200" in excerpt
    assert "+    return unsafe_code()" not in excerpt
    assert controller.has_actionable_review_findings(excerpt)


@pytest.mark.parametrize(
    "review_log",
    [
        "FACTORY_GATE_BLOCKED",
        "semantic blockers remain\nthe pr is returning to repair",
        "# comic-pile-factory-authoritative-diff-evidence\ngh pr diff 3200",
        "diff --git a/app.py b/app.py\n+++ b/app.py\n+const result = unsafe();",
        "```python\ndef broken():\n    return unsafe()\n```",
    ],
)
def test_source_diff_and_verdict_tokens_are_not_repair_findings(review_log: str) -> None:
    controller = load_controller()
    assert not controller.has_actionable_review_findings(review_log)


def test_trusted_ollama_review_preserves_numbered_diff_inspection_proof() -> None:
    """Provider-backed review must preserve the exact PR-scoped diff command."""
    reviewer = (SCRIPTS / "local-ollama-review.sh").read_text()
    assert 'gh_retry gh pr diff "$PR" > /tmp/p.patch' in reviewer
    assert 'f"# comic-pile-factory-authoritative-diff-evidence\\ngh pr diff {pr}\\n"' in reviewer

    controller = load_controller()
    excerpt = controller.semantic_review_excerpt(
        "### Factory semantic review\\n"
        + controller.AUTHORITATIVE_DIFF_EVIDENCE
        + "\\ngh pr diff 4828\\nFACTORY_ACCEPTANCE_V1={}\\n"
    )
    assert "gh pr diff 4828" in excerpt
    assert controller.DIFF_INSPECTION_RE.search(excerpt)


def test_worker_proves_diff_inspection_without_append_of_diff_hunks() -> None:
    worker = (SCRIPTS / "free-model-factory-worker.sh").read_text()
    assert 'if ! gh pr diff "$NUMBER" >/dev/null; then' in worker
    assert 'gh pr diff "$NUMBER" 2>/dev/null | head -n 4000' not in worker
    assert "# comic-pile-factory-authoritative-diff-evidence" in worker
