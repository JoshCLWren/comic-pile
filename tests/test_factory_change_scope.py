"""Deterministic change-scope merge guard (incident #3964).

PR #3964 declared ``Closes #3609`` but changed only a scratch repro test plus
unrelated ``frontend/pnpm-lock.yaml`` churn. Worker, semantic review, Greptile,
PR-Agent and CI all passed it and the drain merged it. These tests pin the
model-free guard the review controller now runs inside the exact-head
mechanical merge gate.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"
WORKFLOWS = ROOT / ".github" / "workflows"
sys.path.insert(0, str(SCRIPTS))

scope = importlib.import_module("factory_change_scope")

HEAD = "4c49695a1f83c8c61bd1a7cb56fee06c9b98a187"
# Assembled so this file never carries the literal throwaway phrase itself.
THROWAWAY = "removed " + "before commit"


def load_controller() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "factory_review_controller_scope", SCRIPTS / "factory-review-controller.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def issue(*labels: str) -> dict[str, Any]:
    return {"state": "open", "labels": [{"name": label} for label in labels]}


def changed(filename: str, status: str = "modified", patch: str = "") -> dict[str, Any]:
    return {"filename": filename, "status": status, "patch": patch}


def pr3964_files() -> list[dict[str, Any]]:
    """The exact file list (and repro header) PR #3964 merged."""
    return [
        changed(
            "frontend/pnpm-lock.yaml",
            patch="@@ -1,3 +1,3 @@\n-  vite: 7.1.0\n+  vite: 7.1.4\n",
        ),
        changed(
            "frontend/src/unit/Issue3609Repro.test.tsx",
            status="added",
            patch=(
                "@@ -0,0 +1,3 @@\n+/* eslint-disable */\n"
                f"+// Scratch reproduction for #3609 \u2014 {THROWAWAY}.\n"
                "+import { render } from '@testing-library/react'\n"
            ),
        ),
    ]


PR3964_BODY = (
    "Closes #3609.\n\nModel: mimo-v2.6-flash-free\nSource: opencode-free\n"
    "Worker: opencode-free-model-factory-58\n"
)
PR3964_BRANCH = "factory/58-3609-opencode-free"


# --- regression: PR #3964 ---------------------------------------------------


def test_pr_3964_file_list_is_denied_with_every_reason() -> None:
    result = scope.evaluate_change_scope(
        files=pr3964_files(),
        body=PR3964_BODY,
        branch=PR3964_BRANCH,
        issues={3609: issue("bug", "ralph-priority:high", "frontend", "factory")},
    )
    assert result["decision"] == "deny"
    reason = result["reason"]
    assert "Issue3609Repro.test.tsx" in reason and "scratch/repro" in reason
    assert "`frontend/pnpm-lock.yaml`" in reason and "manifest" in reason
    assert "closes #3609 but changes no non-test application code" in reason


def test_pr_3964_is_denied_even_when_only_branch_links_the_issue() -> None:
    result = scope.evaluate_change_scope(
        files=[changed("frontend/src/unit/PlanApply.test.tsx", "added")],
        body="no closing keyword here",
        branch=PR3964_BRANCH,
        issues={3609: issue("bug")},
    )
    assert result["decision"] == "deny"
    assert "#3609" in result["reason"]


def test_pr_3964_shape_with_real_fix_passes() -> None:
    files = [
        changed("frontend/src/hooks/useContinuityPlannerEditor.ts"),
        changed("frontend/src/unit/continuityPlannerApply.test.tsx", "added"),
    ]
    result = scope.evaluate_change_scope(
        files=files, body=PR3964_BODY, branch=PR3964_BRANCH, issues={3609: issue("bug")}
    )
    assert result == {
        "decision": "pass",
        "reason": "change scope is consistent with the closed issues",
    }


# --- empty-fix rule -----------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_roll.py",
        "frontend/src/unit/foo.test.tsx",
        "frontend/src/components/__tests__/Thing.tsx",
        "frontend/src/test/fixtures.ts",
        "frontend/src/pages/Queue.spec.ts",
        "app/services/test_helpers_test.py",
        "docs/plan.md",
        ".github/scripts/factory-visibility.cjs",
        "scripts/lint.sh",
    ],
)
def test_non_app_only_changes_cannot_close_a_bug(path: str) -> None:
    result = scope.evaluate_change_scope(
        files=[changed(path)], body="Fixes #10", branch="feature/x", issues={10: issue("bug")}
    )
    assert result["decision"] == "deny"
    assert "changes no non-test application code" in result["reason"]


@pytest.mark.parametrize(
    "path",
    [
        "app/routers/queue.py",
        "comic_pile/queue.py",
        "api/index.py",
        "alembic/versions/abc_fix.py",
        "frontend/src/pages/QueuePage.tsx",
        "frontend/src/hooks/useThing.ts",
        "frontend/index.html",
        "vercel.json",
    ],
)
def test_app_code_change_satisfies_the_empty_fix_rule(path: str) -> None:
    result = scope.evaluate_change_scope(
        files=[changed(path)], body="Closes #10", branch=None, issues={10: issue("bug")}
    )
    assert result["decision"] == "pass", result


def test_deleted_app_code_counts_as_an_app_change() -> None:
    result = scope.evaluate_change_scope(
        files=[changed("app/services/dead.py", "removed")],
        body="Resolves #10",
        branch=None,
        issues={10: issue("bug")},
    )
    assert result["decision"] == "pass"


def test_pr_that_closes_nothing_is_not_subject_to_the_empty_fix_rule() -> None:
    result = scope.evaluate_change_scope(
        files=[changed("tests/test_roll.py")], body="Refs #10", branch="ops/x", issues={}
    )
    assert result["decision"] == "pass"


@pytest.mark.parametrize("label", ["docs", "documentation", "testing", "ops", "ci-infrastructure"])
def test_non_bug_docs_ops_test_issues_may_close_without_app_code(label: str) -> None:
    result = scope.evaluate_change_scope(
        files=[changed("docs/x.md"), changed("tests/test_x.py")],
        body="Closes #11",
        branch=None,
        issues={11: issue(label)},
    )
    assert result["decision"] == "pass"


def test_generic_docs_label_does_not_exempt_a_bug() -> None:
    result = scope.evaluate_change_scope(
        files=[changed("tests/test_x.py")],
        body="Closes #11",
        branch=None,
        issues={11: issue("bug", "testing")},
    )
    assert result["decision"] == "deny"


def test_explicit_test_only_label_exempts_even_a_bug() -> None:
    result = scope.evaluate_change_scope(
        files=[changed("tests/test_x.py")],
        body="Closes #11",
        branch=None,
        issues={11: issue("bug", "test-only")},
    )
    assert result["decision"] == "pass"


def test_every_closed_issue_must_be_exempt() -> None:
    result = scope.evaluate_change_scope(
        files=[changed("tests/test_x.py")],
        body="Closes #11\nFixes #12",
        branch=None,
        issues={11: issue("docs"), 12: issue("enhancement")},
    )
    assert result["decision"] == "deny"
    assert "#11, #12" in result["reason"]


def test_explicit_body_marker_allows_no_app_code() -> None:
    result = scope.evaluate_change_scope(
        files=[changed("tests/test_x.py")],
        body=f"Closes #11\n{scope.NO_APP_CODE_MARKER}",
        branch=None,
        issues={11: issue("bug")},
    )
    assert result["decision"] == "pass"


def test_manual_only_ops_pr_is_exempt_unless_it_closes_a_bug() -> None:
    files = [changed(".github/scripts/factory-review-controller.py")]
    ops = scope.evaluate_change_scope(
        files=files,
        body=f"Closes #20\n{scope.MANUAL_ONLY_MARKER}",
        branch="infra/x",
        issues={20: issue("enhancement")},
    )
    assert ops["decision"] == "pass"
    bug = scope.evaluate_change_scope(
        files=files,
        body=f"Closes #21\n{scope.MANUAL_ONLY_MARKER}",
        branch="infra/x",
        issues={21: issue("bug")},
    )
    assert bug["decision"] == "deny"


def test_linked_closing_references_are_honored() -> None:
    result = scope.evaluate_change_scope(
        files=[changed("tests/test_x.py")],
        body="",
        branch=None,
        issues={30: issue("bug")},
        linked=[30],
    )
    assert result["decision"] == "deny"
    assert "#30" in result["reason"]


def test_unreadable_closing_issue_retries_instead_of_passing() -> None:
    result = scope.evaluate_change_scope(
        files=[changed("tests/test_x.py")], body="Closes #31", branch=None, issues={}
    )
    assert result["decision"] == "retry"


@pytest.mark.parametrize("files", [None, [], [{"status": "added"}], "nope"])
def test_unreadable_file_list_retries(files: object) -> None:
    result = scope.evaluate_change_scope(files=files, body="", branch=None, issues={})
    assert result["decision"] == "retry"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("Closes #1", [1]),
        ("fixes #2 and resolves #3", [2, 3]),
        ("Fixed: #4", [4]),
        ("closed JoshCLWren/comic-pile#5", [5]),
        ("see #6, refs #7", []),
    ],
)
def test_closing_issue_numbers(body: str, expected: list[int]) -> None:
    assert scope.closing_issue_numbers(body=body, branch=None) == expected


# --- lockfile rule ---------------------------------------------------------


def test_lockfile_with_its_manifest_passes() -> None:
    result = scope.evaluate_change_scope(
        files=[changed("frontend/pnpm-lock.yaml"), changed("frontend/package.json")],
        body="",
        branch=None,
        issues={},
    )
    assert result["decision"] == "pass"


def test_root_workspace_lockfile_accepts_member_manifest() -> None:
    result = scope.evaluate_change_scope(
        files=[changed("pnpm-lock.yaml"), changed("frontend/package.json")],
        body="",
        branch=None,
        issues={},
    )
    assert result["decision"] == "pass"


def test_nested_lockfile_does_not_accept_a_root_manifest() -> None:
    result = scope.evaluate_change_scope(
        files=[changed("frontend/pnpm-lock.yaml"), changed("package.json")],
        body="",
        branch=None,
        issues={},
    )
    assert result["decision"] == "deny"
    assert "`frontend/pnpm-lock.yaml`" in result["reason"]


@pytest.mark.parametrize("lockfile", ["uv.lock", "pnpm-lock.yaml", "frontend/pnpm-lock.yaml"])
def test_orphan_lockfile_is_denied_even_alongside_app_code(lockfile: str) -> None:
    result = scope.evaluate_change_scope(
        files=[changed(lockfile), changed("app/main.py")], body="", branch=None, issues={}
    )
    assert result["decision"] == "deny"
    assert "lockfile changed without a matching manifest change" in result["reason"]


def test_uv_lock_with_pyproject_passes() -> None:
    result = scope.evaluate_change_scope(
        files=[changed("uv.lock"), changed("pyproject.toml")], body="", branch=None, issues={}
    )
    assert result["decision"] == "pass"


def test_lockfile_only_marker_or_dependencies_issue_allows_refresh() -> None:
    marker = scope.evaluate_change_scope(
        files=[changed("uv.lock")],
        body=scope.LOCKFILE_ONLY_MARKER,
        branch=None,
        issues={},
    )
    assert marker["decision"] == "pass"
    deps = scope.evaluate_change_scope(
        files=[changed("uv.lock")],
        body="Closes #40",
        branch=None,
        issues={40: issue("dependencies")},
    )
    assert deps["decision"] == "pass"


def test_skills_lock_and_blocking_named_files_are_not_lockfiles() -> None:
    result = scope.evaluate_change_scope(
        files=[changed("skills-lock.json"), changed("frontend/src/hooks/useQueueBlockingInfo.ts")],
        body="",
        branch=None,
        issues={},
    )
    assert result["decision"] == "pass"


# --- scratch rule ----------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "frontend/src/unit/Issue3609Repro.test.tsx",
        "tests/test_issue_99_repro.py",
        "app/scratch.py",
        "frontend/src/ScratchPad.tsx",
        "tests/reproduction_3609.py",
    ],
)
def test_scratch_named_files_are_denied(path: str) -> None:
    result = scope.evaluate_change_scope(
        files=[changed(path, "added"), changed("app/main.py")], body="", branch=None, issues={}
    )
    assert result["decision"] == "deny"
    assert "scratch/repro" in result["reason"]


@pytest.mark.parametrize(
    "path",
    [
        "frontend/src/hooks/useReproducibleSeed.ts",
        "app/services/scratchpad_cache.py",
        "archive/scripts-oneoff/create_ultimate_universe_from_scratch.py",
    ],
)
def test_scratch_name_rule_avoids_obvious_false_positives(path: str) -> None:
    result = scope.evaluate_change_scope(files=[changed(path)], body="", branch=None, issues={})
    assert result["decision"] == "pass", result


def test_removing_a_scratch_file_is_allowed() -> None:
    result = scope.evaluate_change_scope(
        files=[changed("frontend/src/unit/Issue3609Repro.test.tsx", "removed")],
        body="",
        branch=None,
        issues={},
    )
    assert result["decision"] == "pass"


@pytest.mark.parametrize(
    "line",
    [
        f"// {THROWAWAY.capitalize()}",
        f"# temp: {THROWAWAY}",
        "/* delete " + "this before merging */",
        " * Scratch " + "test for the apply flow",
    ],
)
def test_throwaway_comment_markers_are_denied(line: str) -> None:
    patch = f"@@ -0,0 +1,2 @@\n+{line}\n+export const x = 1\n"
    result = scope.evaluate_change_scope(
        files=[changed("frontend/src/pages/Plan.tsx", "modified", patch)],
        body="",
        branch=None,
        issues={},
    )
    assert result["decision"] == "deny"
    assert "throwaway marker" in result["reason"]


def test_throwaway_phrase_in_code_string_or_removed_line_is_ignored() -> None:
    patch = (
        "@@ -1,2 +1,2 @@\n"
        f"-// {THROWAWAY}\n"
        f'+echo "Remove these ignores {THROWAWAY.split()[1]} committing."\n'
    )
    result = scope.evaluate_change_scope(
        files=[changed("scripts/lint.sh", "modified", patch)], body="", branch=None, issues={}
    )
    assert result["decision"] == "pass", result


def test_throwaway_phrase_in_markdown_is_ignored() -> None:
    patch = f"@@ -0,0 +1 @@\n+# Note: {THROWAWAY}\n"
    result = scope.evaluate_change_scope(
        files=[changed("docs/notes.md", "added", patch)], body="", branch=None, issues={}
    )
    assert result["decision"] == "pass"


def test_current_repository_tree_has_no_false_positive_scratch_hits_except_3609() -> None:
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    rows = []
    for path in tracked:
        full = ROOT / path
        patch = ""
        if full.suffix in scope.SCANNED_CONTENT_EXTENSIONS and full.is_file():
            if full.stat().st_size < 1_000_000:
                text = full.read_text(errors="replace")
                patch = "\n".join(f"+{line}" for line in text.splitlines())
        rows.append({"filename": path, "status": "added", "patch": patch})
    hits = scope.scratch_findings(rows)
    assert all("Issue3609Repro" in hit for hit in hits), hits


# --- path classification ---------------------------------------------------


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("frontend/pnpm-lock.yaml", "lockfile"),
        ("uv.lock", "lockfile"),
        ("frontend/src/unit/Issue3609Repro.test.tsx", "test"),
        ("frontend/src/unit/setup.ts", "test"),
        ("tests_e2e/README.md", "test"),
        ("frontend/src/pages/ContinuityPlannerPage.tsx", "app"),
        ("app/main.py", "app"),
        ("frontend/package.json", "app"),
        ("pnpm-workspace.yaml", "manifest"),
        ("docs/AUTONOMOUS_FACTORY_POLICY.md", "other"),
        (".github/workflows/ci.yml", "other"),
    ],
)
def test_classify_path(path: str, kind: str) -> None:
    assert scope.classify_path(path) == kind


# --- controller integration -------------------------------------------------


def fake_gh_json(files: list[dict[str, Any]], linked: list[int]) -> Callable[..., object]:
    def _gh_json(args: list[str], *, input_json: object | None = None) -> object:
        joined = " ".join(args)
        if "/files" in joined:
            return [files]
        if "closingIssuesReferences" in joined:
            return {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "closingIssuesReferences": {"nodes": [{"number": n} for n in linked]}
                        }
                    }
                }
            }
        raise AssertionError(f"unexpected gh call: {joined}")

    return _gh_json


def test_controller_change_scope_gate_denies_pr_3964(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = load_controller()
    monkeypatch.setattr(
        controller,
        "pr_json",
        lambda _n: {"headRefOid": HEAD, "headRefName": PR3964_BRANCH, "body": PR3964_BODY},
    )
    monkeypatch.setattr(controller, "gh_json", fake_gh_json(pr3964_files(), [3609]))
    monkeypatch.setattr(controller, "target_json", lambda n: issue("bug", "frontend"))
    result = controller.change_scope_gate(3964, HEAD)
    assert result["decision"] == "deny"
    assert "closes #3609" in result["reason"]


def test_controller_change_scope_gate_retries_when_files_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = load_controller()
    monkeypatch.setattr(
        controller, "pr_json", lambda _n: {"headRefOid": HEAD, "headRefName": "", "body": ""}
    )

    def broken(args: list[str], *, input_json: object | None = None) -> object:
        raise RuntimeError("gh api failed (1): HTTP 502")

    monkeypatch.setattr(controller, "gh_json", broken)
    result = controller.change_scope_gate(3964, HEAD)
    assert result["decision"] == "retry"


def test_controller_change_scope_gate_retries_when_issue_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = load_controller()
    monkeypatch.setattr(
        controller,
        "pr_json",
        lambda _n: {"headRefOid": HEAD, "headRefName": PR3964_BRANCH, "body": PR3964_BODY},
    )
    monkeypatch.setattr(controller, "gh_json", fake_gh_json(pr3964_files(), []))

    def broken(_n: int) -> dict[str, Any]:
        raise RuntimeError("gh api failed")

    monkeypatch.setattr(controller, "target_json", broken)
    assert controller.change_scope_gate(3964, HEAD)["decision"] == "retry"


def test_mechanical_merge_gate_runs_scope_before_checks_and_reviews(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = load_controller()
    calls: list[str] = []
    monkeypatch.setattr(
        controller,
        "poll_mergeable_gate",
        lambda *_a, **_k: calls.append("mergeable") or {"decision": "pass", "reason": "ok"},
    )
    monkeypatch.setattr(
        controller,
        "change_scope_gate",
        lambda *_a: (
            calls.append("scope") or {"decision": "deny", "reason": "change-scope guard: x"}
        ),
    )
    monkeypatch.setattr(
        controller,
        "required_checks_gate",
        lambda *_a: calls.append("checks") or {"decision": "pass", "reason": "ok"},
    )
    monkeypatch.setattr(
        controller,
        "current_head_review_gate",
        lambda *_a: calls.append("reviews") or {"decision": "pass", "reason": "ok"},
    )
    result = controller.mechanical_merge_gate(3964, HEAD)
    assert result == {"decision": "deny", "reason": "change-scope guard: x"}
    assert calls == ["mergeable", "scope"]


def test_demote_ready_persists_the_gate_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = load_controller()
    monkeypatch.setattr(
        controller,
        "pr_json",
        lambda _n: {
            "state": "OPEN",
            "headRefOid": HEAD,
            "headRefName": PR3964_BRANCH,
            "labels": [{"name": "factory:ready"}],
        },
    )
    posted: list[dict[str, Any]] = []
    labels: list[tuple[int, str, str]] = []
    monkeypatch.setattr(controller, "post_review_comment", lambda **kw: posted.append(kw))
    monkeypatch.setattr(
        controller, "replace_factory_labels", lambda n, o, s: labels.append((n, o, s))
    )
    monkeypatch.setattr(controller, "target_json", lambda _n: issue("bug"))
    result = controller.demote_ready(3964, "change-scope guard: PR closes #3609 but ...")
    assert result == {"status": "demoted", "pr": 3964}
    assert posted and "closes #3609" in posted[0]["excerpt"]
    assert posted[0]["verdict"] == "repair"
    assert (3964, "factory:unowned", "factory:changes-requested") in labels


def test_demote_ready_without_reason_posts_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = load_controller()
    monkeypatch.setattr(
        controller,
        "pr_json",
        lambda _n: {"state": "OPEN", "headRefName": "x", "labels": [{"name": "factory:ready"}]},
    )
    posted: list[dict[str, Any]] = []
    monkeypatch.setattr(controller, "post_review_comment", lambda **kw: posted.append(kw))
    monkeypatch.setattr(controller, "replace_factory_labels", lambda *a: None)
    controller.demote_ready(1)
    assert posted == []


@pytest.mark.parametrize(
    "workflow", ["factory-ready-merge-drain.yml", "fixed-model-factory-dispatch.yml"]
)
def test_merge_workflows_route_denials_with_reason(workflow: str) -> None:
    text = (WORKFLOWS / workflow).read_text()
    assert 'gates --pr "$pr" --expected-head' in text
    assert 'demote-ready --pr "$pr" --reason "$gate_reason"' in text


# --- reviewer mission ------------------------------------------------------


def test_review_mission_carries_scope_contract_and_authoritative_files(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1 $2" == "pr diff" ]]; then\n'
        "  printf 'frontend/pnpm-lock.yaml\\nfrontend/src/unit/Issue3609Repro.test.tsx\\n'\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n"
    )
    gh.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_REPOSITORY": "JoshCLWren/comic-pile",
        "FACTORY_GREPTILE_OUTCOMES_FILE": str(tmp_path / "outcomes.json"),
    }
    script = (
        f"source {SCRIPTS / 'factory-review-findings.sh'}; "
        f"factory_review_findings_mission 3964 {HEAD} {tmp_path / 'findings.md'}"
    )
    result = subprocess.run(
        ["bash", "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "SCOPE AND ACCEPTANCE CHECK" in out
    assert "acceptance criterion" in out
    assert "never a local git diff against origin/main" in out
    assert "a test-only PR must not close a bug" in out
    assert "frontend/src/unit/Issue3609Repro.test.tsx" in out
    assert out.index("SCOPE AND ACCEPTANCE CHECK") < out.index("REVIEW FINDINGS")


def test_markers_are_documented() -> None:
    doc = (ROOT / "docs" / "AUTONOMOUS_FACTORY_POLICY.md").read_text()
    for marker in (scope.NO_APP_CODE_MARKER, scope.LOCKFILE_ONLY_MARKER):
        assert marker in doc
    assert "`test-only`" in doc and "`factory-execution:manual-only`" not in doc
    assert "<!-- factory-execution:manual-only -->" in doc


# --- trusted staging --------------------------------------------------------

WORKER_SCRIPTS = (
    "free-model-factory-worker.sh",
    "free-model-factory-worker-primitives.sh",
    "nvidia-factory-worker.sh",
    "omniroute-factory-worker.sh",
)


@pytest.mark.parametrize("name", WORKER_SCRIPTS)
def test_every_worker_stages_the_change_scope_guard_with_the_controller(name: str) -> None:
    source = (SCRIPTS / name).read_text()
    assert (
        'cp .github/scripts/factory_change_scope.py "$trusted_dir/factory_change_scope.py"'
        in source
    )


def test_staged_trusted_controller_imports_the_guard(tmp_path: Path) -> None:
    """The worker's trusted controller copy must import outside the checkout."""
    source = (SCRIPTS / "free-model-factory-worker.sh").read_text()
    staged = tmp_path / "trusted"
    staged.mkdir()
    for line in source.splitlines():
        line = line.strip()
        if not line.startswith("cp ") or '"$trusted_dir/' not in line:
            continue
        src = line.split()[1]
        dest = line.split('"$trusted_dir/')[1].rstrip('"')
        (staged / dest).write_bytes((ROOT / src).read_bytes())
    check = (
        "import importlib.util, sys\n"
        "spec = importlib.util.spec_from_file_location('c', sys.argv[1] + "
        "'/factory-review-controller.py')\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "assert callable(m.change_scope_gate)\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", check, str(staged)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
