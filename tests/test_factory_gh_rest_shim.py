"""Regression coverage for the factory GitHub REST compatibility shim."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SHIM = REPO_ROOT / ".github/scripts/factory-gh-rest-shim.sh"


def _fake_gh(tmp_path: Path) -> Path:
    fake = tmp_path / "gh-real"
    fake.write_text(
        """#!/usr/bin/env bash
set -Eeuo pipefail
[[ "$1" == api ]] || { echo "unexpected command: $*" >&2; exit 9; }
shift
[[ "${1:-}" == --paginate ]] && shift || true
[[ "${1:-}" == --slurp ]] && shift || true
endpoint="$1"
case "$endpoint" in
  *'/issues?'*)
    printf '%s\\n' '[[{"number":10,"title":"Issue","body":"body","state":"open","created_at":"2026-08-16T00:00:00Z","updated_at":"2026-08-16T01:00:00Z","labels":[{"name":"factory:13"},{"name":"bug"}]},{"number":11,"title":"PR row","body":"body","state":"open","pull_request":{},"created_at":"2026-08-16T00:00:00Z","updated_at":"2026-08-16T01:00:00Z","labels":[{"name":"factory:13"}]}]]'
    ;;
  *'/pulls?'*)
    printf '%s\\n' '[[{"number":20,"title":"PR","body":"pbody","state":"open","draft":false,"created_at":"2026-08-16T00:00:00Z","updated_at":"2026-08-16T01:00:00Z","labels":[{"name":"factory:13"}],"head":{"ref":"factory/13-10-x","sha":"abc"}}]]'
    ;;
  *'/pulls/20')
    printf '%s\\n' '{"number":20,"title":"PR","body":"pbody","state":"open","merged_at":null,"mergeable":true,"draft":false,"labels":[{"name":"factory:13"}],"head":{"ref":"factory/13-10-x","sha":"abc"}}'
    ;;
  *'/issues/10')
    printf '%s\\n' '{"number":10,"title":"Issue","body":"body","state":"open","labels":[{"name":"factory:13"}]}'
    ;;
  *) echo "unknown endpoint: $endpoint" >&2; exit 8 ;;
esac
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return fake


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "FACTORY_REAL_GH": str(_fake_gh(tmp_path)),
            "GITHUB_REPOSITORY": "JoshCLWren/comic-pile",
        }
    )
    return subprocess.run(
        ["bash", str(SHIM), *args],
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )


def test_rest_shim_lists_only_matching_issues(tmp_path: Path) -> None:
    """Issue enumeration avoids GraphQL and excludes pull-request rows."""
    result = _run(
        tmp_path,
        "issue",
        "list",
        "--state",
        "open",
        "--limit",
        "300",
        "--label",
        "factory:13",
        "--json",
        "number",
    )
    assert [item["number"] for item in json.loads(result.stdout)] == [10]


def test_rest_shim_normalizes_pr_list_and_view(tmp_path: Path) -> None:
    """PR enumeration and view expose the fields used by factory wrappers."""
    listed = _run(
        tmp_path,
        "pr",
        "list",
        "--state",
        "open",
        "--limit",
        "200",
        "--label",
        "factory:13",
        "--json",
        "number,labels",
    )
    assert [item["number"] for item in json.loads(listed.stdout)] == [20]

    viewed = _run(
        tmp_path,
        "pr",
        "view",
        "20",
        "--json",
        "headRefName",
        "--jq",
        ".headRefName",
    )
    assert viewed.stdout.strip() == "factory/13-10-x"


def test_rest_shim_normalizes_issue_view_state(tmp_path: Path) -> None:
    """Issue view preserves the uppercase state contract expected by workers."""
    viewed = _run(
        tmp_path,
        "issue",
        "view",
        "10",
        "--json",
        "state",
        "--jq",
        ".state",
    )
    assert viewed.stdout.strip() == "OPEN"


def test_dispatcher_and_worker_install_rest_shim() -> None:
    """Both control-plane assignment and lease consumption use the REST shim."""
    dispatcher = (
        REPO_ROOT / ".github/workflows/free-model-factory-dispatch.yml"
    ).read_text(encoding="utf-8")
    worker = (
        REPO_ROOT / ".github/scripts/free-model-factory-worker.sh"
    ).read_text(encoding="utf-8")

    assert "Install REST-backed factory GitHub reads" in dispatcher
    assert "factory-gh-rest-shim.sh" in dispatcher
    assert "Unable to enumerate factory:ready PRs" in dispatcher
    assert "install_factory_rest_gh" in worker
    assert "factory-gh-rest-shim.sh" in worker
