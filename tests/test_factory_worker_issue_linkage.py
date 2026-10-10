"""Executable regressions for controller/worker PR identity agreement."""

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"


def shell_function(path: Path, name: str) -> str:
    """Extract a shell helper without running the worker entrypoint."""
    match = re.search(rf"(?m)^{name}\(\) \{{\n.*?^\}}", path.read_text(), re.DOTALL)
    assert match is not None
    return match.group(0)


@pytest.mark.parametrize(
    ("branch", "body", "title", "expected"),
    [
        ("fix/3271-durable-review-migration-handoff", "Closes #3271.", "repair", "3271"),
        ("factory/45-2553-catalog-free", "Closes #99", "cutover", "2553"),
        ("local/repair", "References #99", "Fix #3271: handoff", "3271"),
        ("local/repair", "References #99", "repair", ""),
    ],
)
def test_worker_uses_controller_linkage(
    branch: str, body: str, title: str, expected: str
) -> None:
    """Non-roster branch names resolve through body/title with canonical precedence."""
    function = shell_function(SCRIPTS / "free-model-factory-worker-primitives.sh", "linked_issue_from_pr")
    payload = json.dumps({"headRefName": branch, "body": body, "title": title})
    result = subprocess.run(
        ["bash", "-c", function + '\ngh() { printf "%s" "$TEST_PR_JSON"; }\nlinked_issue_from_pr 3314'],
        env={**os.environ, "TEST_PR_JSON": payload, "TRUSTED_REVIEW_CONTROLLER": str(SCRIPTS / "factory-review-controller.py")},
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


@pytest.mark.parametrize("response", ["api-failure", "malformed-json"])
def test_linkage_read_failure_is_not_an_unrelated_issue(response: str) -> None:
    """Unavailable identity fails closed rather than inventing a missing link."""
    function = shell_function(SCRIPTS / "free-model-factory-worker-primitives.sh", "linked_issue_from_pr")
    stub = 'gh() { return 1; }' if response == "api-failure" else 'gh() { printf "invalid"; }'
    result = subprocess.run(
        ["bash", "-c", function + "\n" + stub + "\nlinked_issue_from_pr 3314"],
        env={**os.environ, "TRUSTED_REVIEW_CONTROLLER": str(SCRIPTS / "factory-review-controller.py")},
        text=True, capture_output=True, check=False,
    )
    assert result.returncode != 0
    assert result.stdout == ""


def test_assignment_accepts_local_pr_and_its_controller_leased_issue() -> None:
    """Reproduce #3314's complete lease pair through the actual selector."""
    script = shell_function(SCRIPTS / "free-model-factory-worker-primitives.sh", "linked_issue_from_pr")
    script += "\n" + shell_function(SCRIPTS / "free-model-factory-worker.sh", "select_controller_assignment")
    script += '''
OWNER=factory:54
log() { printf '%s\\n' "$*" >&2; }
gh() {
  if [[ "$1 $2" == 'pr list' ]]; then
    printf '%s' '[{"number":3314,"labels":[{"name":"factory:review"}]}]'
  elif [[ "$1 $2" == 'issue list' ]]; then
    printf '%s' '[{"number":3271}]'
  elif [[ "$*" == *'--json headRefName --jq'* ]]; then
    printf '%s' 'fix/3271-durable-review-migration-handoff'
  else
    printf '%s' '{"headRefName":"fix/3271-durable-review-migration-handoff","body":"Closes #3271.","title":"repair"}'
  fi
}
select_controller_assignment || exit "$?"
printf '%s:%s:%s' "$MODE" "$NUMBER" "$ASSIGNED_PR_STAGE"
'''
    result = subprocess.run(
        ["bash", "-c", script],
        env={**os.environ, "TRUSTED_REVIEW_CONTROLLER": str(SCRIPTS / "factory-review-controller.py")},
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "pr:3314:factory:review"
