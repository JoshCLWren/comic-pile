"""Factory-only fast-merge policy and trusted workflow integration contracts."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github/scripts/factory-fast-merge.py"
SPEC = importlib.util.spec_from_file_location("factory_fast_merge", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)
REPO = "JoshCLWren/comic-pile"
HEAD = "a" * 40


def candidate() -> dict:
    """Return a trusted same-repo unowned factory PR."""
    return {
        "state": "open",
        "draft": False,
        "mergeable": True,
        "base": {"ref": "main", "repo": {"full_name": REPO}},
        "head": {"sha": HEAD, "repo": {"full_name": REPO}},
        "author_association": "OWNER",
        "user": {"login": "JoshCLWren"},
        "labels": [
            {"name": "factory"},
            {"name": "factory:unowned"},
            {"name": "factory:changes-requested"},
        ],
        "changed_files": 1,
    }


def files(path: str = ".github/scripts/factory-work-controller.py") -> list[dict]:
    """Return one changed path."""
    return [{"filename": path, "status": "modified"}]


def test_factory_only_review_rejected_stage_is_eligible() -> None:
    """Owner-selected factory-only code may bypass semantic review."""
    allowed, _ = gate.factory_candidate(candidate(), files(), REPO)
    assert allowed


@pytest.mark.parametrize(
    "path",
    [
        "app/main.py",
        "api/index.py",
        ".github/workflows/ci.yml",
        ".github/workflows/deploy-production.yml",
        ".github/scripts/factory-fast-merge.py",
        ".github/workflows/factory-fast-merge.yml",
        ".github/factory-fast-merge.json",
        "tests/test_factory_fast_merge.py",
        "../.github/scripts/factory-review-controller.py",
        ".github/scripts/generate_factory_status_dashboard.py.bak",
        "frontend/generate_factory_status_dashboard.py",
    ],
)
def test_nonfactory_and_policy_changes_cannot_auto_merge(path: str) -> None:
    """The switch excludes product changes and modifications to itself."""
    assert not gate.factory_path(path)


@pytest.mark.parametrize(
    "path",
    [
        ".github/scripts/factory-review-controller.py",
        ".github/scripts/local_review_contract.py",
        ".github/workflows/fixed-model-factory-dispatch.yml",
        "scripts/factory_eligibility.py",
        "tests/test_factory_work_controller_runtime.py",
        "tests/test_local_ollama_review_contract.py",
        "docs/FACTORY_FAST_MERGE.md",
        ".github/free-model-factories.tsv",
        ".github/factory-expected-workers.json",
        ".github/factory-roster-snapshot.json",
        "tests/test_free_model_factories.py",
        ".github/scripts/generate_factory_status_dashboard.py",
        "tests/test_generate_factory_status_dashboard.py",
    ],
)
def test_supported_factory_paths(path: str) -> None:
    """The known factory-only files are explicitly allowlisted."""
    assert gate.factory_path(path)


def test_mixed_product_pr_is_ineligible() -> None:
    """One product path prevents a factory-only fast merge."""
    pr = candidate()
    pr["changed_files"] = 2
    ok, why = gate.factory_candidate(pr, files() + files("app/main.py"), REPO)
    assert not ok
    assert "allowlist" in why


def test_rename_cannot_smuggle_product_code() -> None:
    """Both sides of a rename must stay inside the factory boundary."""
    changed = [
        {
            "filename": "tests/test_factory_example.py",
            "previous_filename": "api/index.py",
            "status": "renamed",
        }
    ]
    ok, why = gate.factory_candidate(candidate(), changed, REPO)
    assert not ok
    assert "Rename" in why


@pytest.mark.parametrize(
    ("mutation", "value"),
    [
        ("draft", True),
        ("mergeable", None),
        ("author_association", "NONE"),
    ],
)
def test_untrusted_or_unmergeable_pr_is_blocked(
    mutation: str, value: object,
) -> None:
    """Untrusted, draft, or unmergeable candidates fail closed."""
    pr = candidate()
    pr[mutation] = value
    ok, _ = gate.factory_candidate(pr, files(), REPO)
    assert not ok


def test_fork_and_owner_claim_are_blocked() -> None:
    """Only same-repo PRs without an active lease may fast merge."""
    pr = candidate()
    pr["head"]["repo"]["full_name"] = "attacker/fork"
    assert not gate.factory_candidate(pr, files(), REPO)[0]
    pr = candidate()
    pr["labels"].append({"name": "factory:104"})
    assert not gate.factory_candidate(pr, files(), REPO)[0]


def test_unsupported_or_incomplete_file_listing_is_blocked() -> None:
    """Never trust a partial GitHub changed-file listing."""
    pr = candidate()
    pr["changed_files"] = 3000
    assert not gate.factory_candidate(pr, files(), REPO)[0]
    pr["changed_files"] = 2
    assert not gate.factory_candidate(pr, files(), REPO)[0]


def check(name: str, *, head: str = HEAD, result: str = "success", app: str = "github-actions", id: int = 10) -> dict:
    """Simulate one GitHub-issued Python CI check for an exact commit head."""
    return {
        "id": id,
        "name": name,
        "head_sha": head,
        "status": "completed" if result != "pending" else "in_progress",
        "conclusion": None if result == "pending" else result,
        "app": {"slug": app},
    }


def python_ci_rows(*, missing: str = "", fail: str = "", head: str = HEAD, app: str = "github-actions") -> dict:
    """Supply completed, trusted Python CI checks without executing PR code."""
    rows = [
        check(name, result="failure" if name == fail else "success", head=head, app=app, id=index)
        for index, name in enumerate(sorted(gate.REQUIRED_FAST_CHECKS), start=1)
        if name != missing
    ]
    return {"total_count": len(rows), "check_runs": rows}


def test_factory_merge_requires_successful_exact_head_python_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fast lane merges only after reading trusted Ruff and ty evidence."""
    calls: list[tuple[str, str, dict | None]] = []

    def fake_api(
        endpoint: str, *, method: str = "GET", fields: dict | None = None,
    ) -> dict:
        calls.append((endpoint, method, fields))
        if endpoint == f"repos/{REPO}/pulls/123":
            return candidate()
        if endpoint == f"repos/{REPO}/commits/{HEAD}/check-runs?per_page=100":
            return python_ci_rows()
        assert method == "PUT"
        return {"merged": True, "sha": "b" * 40}

    monkeypatch.setattr(gate, "gh_api", fake_api)
    monkeypatch.setattr(gate, "pages", lambda *_args: files())
    did_merge, commit = gate.handle(REPO, 123)
    assert did_merge
    assert commit == "b" * 40
    assert [entry[1] for entry in calls] == ["GET", "GET", "PUT"]
    merge_fields = calls[2][2]
    assert merge_fields is not None
    assert merge_fields["sha"] == HEAD
    assert merge_fields["merge_method"] == "squash"


@pytest.mark.parametrize("rows", [
    {"check_runs": [], "total_count": 0},
    python_ci_rows(missing="Python Lint (ruff)"),
    python_ci_rows(missing="Python Type Check (ty)"),
    python_ci_rows(fail="Python Lint (ruff)"),
    python_ci_rows(fail="Python Type Check (ty)"),
    python_ci_rows(head="b" * 40),
    python_ci_rows(app="untrusted-app"),
    {"check_runs": [], "total_count": 101},
])
def test_missing_or_failing_ci_prevents_fast_merge(
    monkeypatch: pytest.MonkeyPatch, rows: dict,
) -> None:
    """Pending, red, stale, untrusted or truncated CI never authorizes a merge."""
    calls: list[str] = []

    def fake_api(endpoint: str, *, method: str = "GET", fields: dict | None = None) -> dict:
        calls.append(endpoint)
        if endpoint.endswith("/pulls/123"):
            return candidate()
        if endpoint.endswith("/check-runs?per_page=100"):
            return rows
        pytest.fail("Factory fast merge attempted a write without green CI")

    monkeypatch.setattr(gate, "gh_api", fake_api)
    monkeypatch.setattr(gate, "pages", lambda *_args: files())
    did_merge, reason = gate.handle(REPO, 123)
    assert not did_merge
    assert "not passed" in reason or "missing or truncated" in reason
    assert len(calls) == 2


def test_rerun_failure_does_not_let_older_success_authorize_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later failed rerun supersedes prior passing check runs."""
    rows = python_ci_rows()
    rows["check_runs"].append(check("Python Lint (ruff)", id=100, result="failure"))
    rows["total_count"] = 3
    monkeypatch.setattr(
        gate, "gh_api",
        lambda endpoint, **_kwargs: candidate() if endpoint.endswith("/pulls/123") else rows,
    )
    monkeypatch.setattr(gate, "pages", lambda *_args: files())
    allowed, _ = gate.handle(REPO, 123)
    assert not allowed


def test_branch_protection_refusal_is_a_truthful_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After passing CI, GitHub still owns the final ruleset merge decision."""
    def fake_api(
        endpoint: str, *, method: str = "GET", fields: dict | None = None,
    ) -> dict:
        if method == "PUT":
            raise RuntimeError("required status check CI Summary is expected")
        if endpoint.endswith("/pulls/123"):
            return candidate()
        if endpoint.endswith("/check-runs?per_page=100"):
            return python_ci_rows()
        pytest.fail("Unexpected GitHub read")

    monkeypatch.setattr(gate, "gh_api", fake_api)
    monkeypatch.setattr(gate, "pages", lambda *_args: files())
    did_merge, reason = gate.handle(REPO, 123)
    assert not did_merge
    assert "CI Summary" in reason
    assert "rejected immediate merge" in reason

def test_switch_defaults_off_and_explicit_true_enables(tmp_path: Path) -> None:
    """The owner switch fails closed for malformed or absent config."""
    path = tmp_path / "switch.json"
    assert not gate.enabled(path)
    path.write_text('{"enabled": false}', encoding="utf-8")
    assert not gate.enabled(path)
    path.write_text('{"enabled": "true"}', encoding="utf-8")
    assert not gate.enabled(path)
    path.write_text('{"enabled": true}', encoding="utf-8")
    assert gate.enabled(path)


def test_workflow_uses_main_and_immediate_trigger_without_running_pr_code() -> None:
    """Privileged automation checks out trusted main and pins merge SHA."""
    workflow = (ROOT / ".github/workflows/factory-fast-merge.yml").read_text()
    script = SCRIPT.read_text()
    assert "pull_request_target:" in workflow
    assert "workflow_job:" in workflow
    assert "github.event.workflow_job.head_sha" in workflow
    assert "Python Lint (ruff)" in workflow
    assert "Python Type Check (ty)" in workflow
    assert "workflow_run:" not in workflow
    assert "secrets.PR_REBASE_TOKEN" in workflow
    assert "ref: main" in workflow
    assert "persist-credentials: false" in workflow
    assert "factory-fast-merge.py" in workflow
    assert '"sha": head' in script
    assert 'python_checks_passed(repo, head)' in script
    assert "factory_dispatch_production_deploy" in script
    assert "dispatch_production(len(merged))" in script
    assert "factory_post_merge_closure.py --sweep" in workflow


def test_production_dispatch_runs_from_merge_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bot merges schedule a deploy without relying on push events."""
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> object:
        """Record the trusted shell command instead of invoking a workflow."""
        calls.append(args)
        return type("Result", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    gate.dispatch_production(2)
    assert len(calls) == 1
    assert "factory_dispatch_production_deploy" in calls[0][4]
    assert "merged 2 PR(s)" in calls[0][-1]


def test_source_controlled_factory_inventory_cannot_fast_merge() -> None:
    """Even an atomic replacement of all three retired inventory files is blocked."""
    changed = [
        {"filename": filename, "status": "modified"} for filename in (
            ".github/free-model-factories.tsv",
            ".github/factory-expected-workers.json",
            ".github/factory-roster-snapshot.json",
        )
    ]
    pr = candidate()
    pr["changed_files"] = len(changed)
    permitted, detail = gate.factory_candidate(pr, changed, REPO)
    assert not permitted
    assert "inventor" in detail.lower()


def test_removing_all_legacy_inventory_files_is_not_blocked_as_a_model_pin() -> None:
    changed = [
        {"filename": filename, "status": "removed"} for filename in (
            ".github/free-model-factories.tsv",
            ".github/factory-expected-workers.json",
            ".github/factory-roster-snapshot.json",
        )
    ]
    pr = candidate()
    pr["changed_files"] = len(changed)
    # Authorization may still require unrelated review/ownership checks.
    permitted, detail = gate.factory_candidate(pr, changed, REPO)
    assert permitted or "Outside factory-only allowlist" not in detail


@pytest.mark.parametrize(
    "missing_path",
    [
        ".github/free-model-factories.tsv",
        ".github/factory-expected-workers.json",
        ".github/factory-roster-snapshot.json",
    ],
)
def test_partial_factory_roster_cannot_fast_merge(missing_path: str) -> None:
    """Never fast-merge a roster manifest detached from its generated state."""
    changed = [
        {"filename": path, "status": "modified"}
        for path in (
            ".github/free-model-factories.tsv",
            ".github/factory-expected-workers.json",
            ".github/factory-roster-snapshot.json",
        )
        if path != missing_path
    ]
    pr = candidate()
    pr["changed_files"] = len(changed)
    assert not gate.factory_candidate(pr, changed, REPO)[0]
