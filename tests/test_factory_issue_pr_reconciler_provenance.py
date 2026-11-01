"""Regression checks for the trusted issue/PR reconciliation verifier."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/factory-issue-pr-state-reconciler.yml"
BRANCH = "factory/39-1477-opencode-free"
HEAD = "a" * 40
MARKER = (
    "<!-- comic-pile-factory-pr-provenance-v1:"
    f"pr-1517:issue-1477:opencode-free-model-factory-39:1787060686:{HEAD} -->"
)


def _verifier_script() -> str:
    """Extract the actual inline verifier, avoiding a copied test implementation."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"python3 - \"\$head_ref\".*?<<'PY'\n(.*?)\n          PY", workflow, re.DOTALL)
    assert match is not None
    return textwrap.dedent(match.group(1))


@pytest.mark.parametrize(
    ("comments", "expected"),
    [
        ([{"body": MARKER, "user": {"login": "github-actions[bot]"}}], 0),
        ([{"body": "untrusted", "user": {"login": "github-actions[bot]"}}], 1),
        ([{"body": MARKER, "user": {"login": "untrusted-bot"}, "author_association": "NONE"}], 1),
    ],
)
def test_reconciler_provenance_outcomes(
    tmp_path: Path, comments: list[dict[str, object]], expected: int
) -> None:
    """The real verifier accepts only trusted matching provenance."""
    comment_file = tmp_path / "comments.json"
    comment_file.write_text(json.dumps(comments), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-", BRANCH, "1517", "1477", str(comment_file)],
        input=_verifier_script(),
        text=True,
        capture_output=True,
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == expected, result.stderr


def test_reconciler_verifier_error_is_not_missing_provenance(tmp_path: Path) -> None:
    """Operational failures must return 2, never the retryable missing-marker 1."""
    comment_file = tmp_path / "invalid.json"
    comment_file.write_text("{invalid json", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-", BRANCH, "1517", "1477", str(comment_file)],
        input=_verifier_script(),
        text=True,
        capture_output=True,
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 2
    assert "JSONDecodeError" in result.stderr
