"""Fixture tests for the scheduled stale-branch prune workflow and its helpers (issue #4749)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "prune_stale_factory_branches.py"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "stale-branch-prune.yml"
SPEC = importlib.util.spec_from_file_location("prune_stale_factory_branches", SCRIPT_PATH)
assert SPEC and SPEC.loader
prune = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = prune
SPEC.loader.exec_module(prune)

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
OLD_COMMIT = "2026-01-05T09:00:00+00:00"


def _workflow() -> dict[object, object]:
    """Load the scheduled prune workflow as YAML."""
    loaded = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _triggers(workflow: dict[object, object]) -> dict[object, object]:
    """Return the workflow trigger mapping regardless of PyYAML's ``on`` key typing."""
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict)
    return triggers


def _prune_job(workflow: dict[object, object]) -> dict[object, object]:
    """Return the single prune job definition."""
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    prune_job = jobs.get("prune")
    assert isinstance(prune_job, dict)
    return prune_job


def _steps() -> list[dict[object, object]]:
    """Return the prune job's ordered steps."""
    steps = _prune_job(_workflow()).get("steps")
    assert isinstance(steps, list)
    assert all(isinstance(step, dict) for step in steps)
    return steps


def _step_index(steps: Sequence[dict[object, object]], name_fragment: str) -> int:
    """Return the index of the step whose name contains the fragment."""
    matches = [
        index
        for index, step in enumerate(steps)
        if name_fragment in str(step.get("name", ""))
    ]
    assert len(matches) == 1, f"expected one step matching {name_fragment!r}"
    return matches[0]


def _decision(name: str, *, eligible: bool, reasons: tuple[str, ...] = ()) -> prune.Decision:
    """Build a Decision fixture for batch and summary tests."""
    return prune.Decision(
        branch=name,
        sha="abc123",
        action="delete" if eligible else "skip",
        reasons=reasons,
        category="factory/local/backup",
        age_days=20.0,
        merged=True,
        open_pr=False,
        linked_issue=None,
    )


def test_workflow_is_scheduled_least_privilege_and_report_first() -> None:
    """The workflow runs on a schedule, starts read-only and reports before applying."""
    workflow = _workflow()
    triggers = _triggers(workflow)
    assert "schedule" in triggers
    assert "workflow_dispatch" in triggers
    assert workflow.get("permissions") == {"contents": "read"}
    assert _prune_job(workflow).get("permissions") == {
        "contents": "write",
        "issues": "read",
        "pull-requests": "read",
    }
    steps = _steps()
    dry_run = _step_index(steps, "Dry-run report")
    apply = _step_index(steps, "Bounded apply")
    upload = _step_index(steps, "Upload prune reports")
    assert dry_run < apply < upload


def test_workflow_apply_is_bounded_and_records_an_artifact() -> None:
    """The apply step is gated, bounded and writes a report uploaded as an artifact."""
    steps = _steps()
    apply_step = steps[_step_index(steps, "Bounded apply")]
    assert apply_step.get("if") is not None
    apply_run = str(apply_step.get("run", ""))
    assert "--apply" in apply_run
    assert "--max-deletions" in apply_run and "$PRUNE_MAX_DELETIONS" in apply_run
    assert "--report-file" in apply_run and "prune-reports/apply.json" in apply_run
    upload_step = steps[_step_index(steps, "Upload prune reports")]
    assert upload_step.get("if") == "always()"
    options = upload_step.get("with")
    assert isinstance(options, dict)
    assert "prune-reports/" in str(options.get("path", ""))


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        ("http 401 Unauthorized", False),
        ("http 403 Forbidden", False),
        ("http 404 Not Found", False),
        ("http 400 bad request", False),
        ("HTTP 429 too many requests", True),
        ("abuse detection mechanism", True),
        ("502 Bad Gateway", True),
        ("connection reset by peer", True),
        ("unexpected eof", True),
        ("ordinary command failure", False),
    ],
)
def test_retry_classification_distinguishes_terminal_from_transient(
    detail: str, expected: bool
) -> None:
    """Only transient API failures are eligible for a bounded retry."""
    assert prune._is_retryable_api_error(detail) is expected


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        ("retry after 5 seconds", 5.0),
        ("Retry-After: 2 minutes", 60.0),
        ("retry-after 120", 60.0),
        ("no retry hint in this error", None),
    ],
)
def test_retry_after_header_is_capped(detail: str, expected: float | None) -> None:
    """Advertised Retry-After delays are honored but never exceed the cap."""
    assert prune._retry_after_seconds(detail) == expected


def test_run_gh_api_retries_transient_failure_with_bounded_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient GitHub API failure is retried with a capped delay."""
    commands: list[Sequence[str]] = []
    sleeps: list[float] = []
    monkeypatch.setenv("FACTORY_PRUNE_API_ATTEMPTS", "3")
    monkeypatch.setenv("FACTORY_PRUNE_RETRY_SECONDS", "0.01")

    def fake_run(cmd: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        """Fail once with a transient error, then succeed."""
        commands.append(cmd)
        if len(commands) == 1:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="HTTP 429 rate limit")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(prune, "run", fake_run)
    monkeypatch.setattr(prune.time, "sleep", lambda seconds: sleeps.append(seconds))
    result = prune.run_gh_api(["gh", "api", "repos/owner/repo"], label="lookup")

    assert result.stdout == "ok"
    assert len(commands) == 2
    assert len(sleeps) == 1
    assert 0 < sleeps[0] <= prune.MAX_RETRY_DELAY_SECONDS


def test_run_gh_api_does_not_retry_terminal_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auth and not-found failures fail closed without retrying."""
    commands: list[Sequence[str]] = []
    sleeps: list[float] = []
    monkeypatch.setenv("FACTORY_PRUNE_API_ATTEMPTS", "3")

    def fake_run(cmd: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        """Return a terminal authorization failure."""
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="http 401 Unauthorized")

    monkeypatch.setattr(prune, "run", fake_run)
    monkeypatch.setattr(prune.time, "sleep", lambda seconds: sleeps.append(seconds))
    with pytest.raises(RuntimeError, match="lookup"):
        prune.run_gh_api(["gh", "api", "repos/owner/repo"], label="lookup")

    assert len(commands) == 1
    assert sleeps == []


def test_apply_batch_bounds_deletions_and_defers_the_remainder() -> None:
    """Only the bounded batch is deleted; the rest is deferred to a later run."""
    decisions = [
        _decision("factory/11-100-first", eligible=True),
        _decision("backup/protected", eligible=False, reasons=("protected branch",)),
        _decision("factory/12-200-second", eligible=True),
        _decision("factory/13-300-third", eligible=True),
    ]
    batch, deferred = prune.apply_batch(decisions, 2)
    assert [d.branch for d in batch] == ["factory/11-100-first", "factory/12-200-second"]
    assert [d.branch for d in deferred] == ["factory/13-300-third"]


def test_apply_batch_zero_bound_deletes_nothing() -> None:
    """A zero batch bound cannot authorize even one destructive deletion."""
    decisions = [
        _decision("factory/11-100-first", eligible=True),
        _decision("factory/12-200-second", eligible=True),
    ]
    batch, deferred = prune.apply_batch(decisions, 0)
    assert batch == []
    assert [d.branch for d in deferred] == [
        "factory/11-100-first",
        "factory/12-200-second",
    ]


def test_execution_summary_records_before_after_counts_and_protections() -> None:
    """The summary proves the count drop and names protected refs for the artifact."""
    decisions = [
        _decision("factory/deleted", eligible=True),
        _decision("factory/leased", eligible=False, reasons=("active local lease on issue:300",)),
        _decision("factory/pr", eligible=False, reasons=("open PR exists",)),
    ]
    summary = prune.build_execution_summary(
        decisions,
        mode="apply",
        deleted=["factory/deleted"],
        deferred=["factory/next"],
        failures=[],
        branch_count_before=120,
    )
    assert summary["branch_count_before"] == 120
    assert summary["branch_count_after"] == 119
    assert summary["deleted_refs"] == ["factory/deleted"]
    assert summary["deferred_refs"] == ["factory/next"]
    assert summary["skipped_count"] == 2
    assert summary["protected_by_active_lease"] == ["factory/leased"]
    assert summary["protected_by_open_pr"] == ["factory/pr"]


def _git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    """Run a git command in a fixture repository and return stdout."""
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.stdout


def test_apply_run_reduces_branch_count_without_deleting_protected_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real bounded apply against a fixture remote drops only unprotected refs."""
    bare = tmp_path / "remote.git"
    work = tmp_path / "work"
    bare.mkdir()
    work.mkdir()
    _git(bare, "init", "--bare", "--initial-branch=main")
    _git(work, "init", "--initial-branch=main")
    _git(work, "remote", "add", "origin", str(bare))
    _git(work, "config", "user.email", "prune@example.test")
    _git(work, "config", "user.name", "Prune Test")
    (work / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(work, "add", "README.md")
    old_env = dict(os.environ)
    old_env["GIT_AUTHOR_DATE"] = OLD_COMMIT
    old_env["GIT_COMMITTER_DATE"] = OLD_COMMIT
    _git(work, "commit", "-m", "old base", env=old_env)
    _git(work, "push", "origin", "main")

    names = [
        "factory/11-100-old",
        "backup/old-snapshot",
        "factory/12-200-open-pr",
        "local-factory/i300-lease",
        "release/1.0",
    ]
    for name in names:
        _git(work, "branch", name, "main")
        _git(work, "push", "origin", name)

    monkeypatch.chdir(work)
    monkeypatch.setattr(prune, "utc_now", lambda: NOW)
    monkeypatch.setattr(prune, "remote_github_repo", lambda root, remote: "owner/repo")
    monkeypatch.setattr(prune, "local_worktree_branches", lambda root: set())
    monkeypatch.setattr(
        prune, "fetch_protected_branches", lambda repo: {"main", "release/1.0"}
    )

    def fake_pr_records(repo: str) -> dict[str, list[dict[str, object]]]:
        """Report one open PR protecting a single branch."""
        return {
            "factory/12-200-open-pr": [
                {"number": 42, "state": "OPEN", "headRefName": "factory/12-200-open-pr"}
            ]
        }

    def fake_branch_pr_records(repo: str, branch: str) -> list[dict[str, object]]:
        """Return the scoped PR history used by the apply-time recheck."""
        return fake_pr_records(repo).get(branch, [])

    def fake_issue_signal(repo: str, issue_number: int) -> prune.LeaseSignal | None:
        """Report one active local lease protecting the linked branch."""
        if issue_number == 300:
            return prune.LeaseSignal(
                target="issue:300",
                state="open",
                owner="factory:local",
                labels=frozenset({"factory", "factory:local", "factory:building"}),
                updated_at=NOW,
            )
        return None

    monkeypatch.setattr(prune, "fetch_pr_records", fake_pr_records)
    monkeypatch.setattr(prune, "fetch_branch_pr_records", fake_branch_pr_records)
    monkeypatch.setattr(prune, "fetch_issue_signal", fake_issue_signal)
    monkeypatch.setattr(prune, "fetch_issue_retired", lambda repo, issue: False)

    report_file = tmp_path / "apply.json"
    exit_code = prune.main(
        [
            "--repo",
            "owner/repo",
            "--remote",
            "origin",
            "--apply",
            "--max-deletions",
            "2",
            "--format",
            "json",
            "--report-file",
            str(report_file),
        ]
    )

    assert exit_code == 0
    surviving = set(_git(bare, "branch", "--format=%(refname:short)").splitlines())
    assert "main" in surviving
    assert "release/1.0" in surviving
    assert "factory/12-200-open-pr" in surviving
    assert "local-factory/i300-lease" in surviving
    assert "factory/11-100-old" not in surviving
    assert "backup/old-snapshot" not in surviving
    summary = json.loads(report_file.read_text(encoding="utf-8"))["summary"]
    assert summary["branch_count_before"] == 6
    assert summary["branch_count_after"] == 4
    assert summary["deleted_count"] == 2
    assert summary["protected_by_open_pr"] == ["factory/12-200-open-pr"]
    assert summary["protected_by_active_lease"] == ["local-factory/i300-lease"]


def test_workflow_file_triggers_and_permissions_are_documented() -> None:
    """The script docstring's workflow reference resolves to a scheduled caller."""
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    assert ".github/workflows/stale-branch-prune.yml" in script
    assert WORKFLOW_PATH.exists()
    assert "cron:" in WORKFLOW_PATH.read_text(encoding="utf-8")
