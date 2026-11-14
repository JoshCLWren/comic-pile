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


def test_ci_summary_must_be_exact_head_actions_success() -> None:
    """Required status is not replaced by unrelated or stale checks."""
    check = {
        "id": 12,
        "name": "CI Summary",
        "head_sha": HEAD,
        "status": "completed",
        "conclusion": "success",
        "app": {"slug": "github-actions"},
    }
    ci = {
        "name": "CI",
        "head_sha": HEAD,
        "status": "completed",
        "conclusion": "success",
        "event": "pull_request",
    }
    assert gate.ci_passed(HEAD, [check], [ci])
    assert not gate.ci_passed(HEAD, [{**check, "conclusion": "failure"}], [ci])
    assert not gate.ci_passed(HEAD, [{**check, "head_sha": "b" * 40}], [ci])
    assert not gate.ci_passed(HEAD, [{**check, "app": {"slug": "other"}}], [ci])
    assert not gate.ci_passed(HEAD, [check], [{**ci, "conclusion": "failure"}])
    assert not gate.ci_passed(HEAD, [check], [{**ci, "head_sha": "b" * 40}])


def test_latest_ci_summary_controls_decision() -> None:
    """A stale passed attempt cannot mask a newer failure."""
    base = {
        "name": "CI Summary",
        "head_sha": HEAD,
        "status": "completed",
        "app": {"slug": "github-actions"},
    }
    old = {**base, "id": 10, "conclusion": "success"}
    new = {**base, "id": 11, "conclusion": "failure"}
    run = {
        "name": "CI",
        "head_sha": HEAD,
        "status": "completed",
        "conclusion": "success",
        "event": "pull_request",
    }
    assert not gate.ci_passed(HEAD, [old, new], [run])


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


def test_workflow_uses_main_and_ci_trigger_without_running_pr_code() -> None:
    """Privileged automation checks out trusted main and pins merge SHA."""
    workflow = (ROOT / ".github/workflows/factory-fast-merge.yml").read_text()
    script = SCRIPT.read_text()
    assert "pull_request_target:" in workflow
    assert "workflow_run:" in workflow
    assert "workflows: [CI]" in workflow
    assert "ref: main" in workflow
    assert "persist-credentials: false" in workflow
    assert "factory-fast-merge.py" in workflow
    assert '"sha": head' in script
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


def test_complete_factory_roster_change_is_fast_merge_eligible() -> None:
    """Atomic roster edits qualify without expanding the product-code allowlist."""
    changed = [
        {"filename": path, "status": "modified"}
        for path in (
            ".github/free-model-factories.tsv",
            ".github/factory-expected-workers.json",
            ".github/factory-roster-snapshot.json",
            "tests/test_free_model_factories.py",
        )
    ]
    pr = candidate()
    pr["changed_files"] = len(changed)
    assert gate.factory_candidate(pr, changed, REPO) == (True, "Factory-only PR eligible")


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
